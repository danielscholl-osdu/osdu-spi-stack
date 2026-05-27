#!/usr/bin/env bash
# Watch Flux Kustomizations across the cluster and exit when all are Ready.
#
# Designed for the Azure smoke CI job. After `spi up` returns, the AKS Flux
# extension has been told to install via `--no-wait`, so CRDs and the
# GitRepository may not yet exist; reconciliation then proceeds in the
# background. This script:
#
#   1. Polls `kubectl get kustomizations -A` and groups results by the
#      `spi-stack.layer` label so progress is visible per dependency tier.
#   2. Emits a compact heartbeat every --heartbeat seconds so a human
#      tailing the log never sees more than 30s of silence.
#   3. Prints a checkpoint banner the moment a layer flips to fully Ready.
#   4. Dumps `spi status` every --status-interval seconds for the rich
#      table view in the log and one final time on exit (success or fail).
#
# Exit codes:
#   0  every Kustomization Ready=True
#   1  --timeout elapsed, or --grace elapsed before any Kustomization appeared
#   2  prerequisite missing (kubectl/jq)

set -u
set -o pipefail

TIMEOUT=1800
HEARTBEAT=30
STATUS_INTERVAL=180
GRACE=600

usage() {
    cat <<'EOF'
Usage: wait_for_flux_ready.sh [--timeout SECONDS] [--heartbeat SECONDS]
                              [--status-interval SECONDS] [--grace SECONDS]
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --timeout) TIMEOUT="$2"; shift 2 ;;
        --heartbeat) HEARTBEAT="$2"; shift 2 ;;
        --status-interval) STATUS_INTERVAL="$2"; shift 2 ;;
        --grace) GRACE="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
    esac
done

for tool in kubectl jq; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: $tool is required but not on PATH" >&2
        exit 2
    fi
done

fmt_mmss() { printf '%02d:%02d' $(( $1 / 60 )) $(( $1 % 60 )); }

dump_status() {
    if command -v uv >/dev/null 2>&1; then
        uv run spi status 2>&1 || true
    else
        kubectl get kustomizations -A 2>&1 || true
    fi
}

print_banner() {
    echo
    echo "─── $1 ───"
    echo
}

START=$SECONDS
LAST_STATUS=0
SEEN_KUSTOMIZATIONS=0
declare -A LAYER_DONE

print_banner "wait_for_flux_ready · timeout $(fmt_mmss "$TIMEOUT") · heartbeat ${HEARTBEAT}s · spi status every ${STATUS_INTERVAL}s"

while :; do
    elapsed=$(( SECONDS - START ))

    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo
        echo "ERROR: timed out after $(fmt_mmss "$elapsed") waiting for Kustomizations to become Ready" >&2
        echo "Final status:" >&2
        dump_status >&2
        exit 1
    fi

    if ! ksts_json=$(kubectl get kustomizations -A -o json 2>/dev/null); then
        ksts_json='{"items":[]}'
    fi

    total=$(jq -r '.items | length' <<<"$ksts_json")

    if [ "$total" = "0" ]; then
        # The grace window only applies before we have *ever* seen a
        # Kustomization. Once we have, a transient empty response from
        # kubectl (AAD token refresh, brief API throttling, etc.) must
        # not be confused with "Flux extension never installed CRDs."
        if [ "$SEEN_KUSTOMIZATIONS" -eq 0 ] && [ "$elapsed" -ge "$GRACE" ]; then
            echo
            echo "ERROR: no Flux Kustomizations visible after ${GRACE}s grace -- AKS Flux extension never installed CRDs" >&2
            dump_status >&2
            exit 1
        fi
        if [ "$SEEN_KUSTOMIZATIONS" -eq 0 ]; then
            printf '[%s / %s] waiting for Flux extension to surface Kustomizations...\n' \
                "$(fmt_mmss "$elapsed")" "$(fmt_mmss "$TIMEOUT")"
        else
            printf '[%s / %s] transient empty kubectl response; retrying...\n' \
                "$(fmt_mmss "$elapsed")" "$(fmt_mmss "$TIMEOUT")"
        fi
    else
        SEEN_KUSTOMIZATIONS=1
        per_layer=$(jq -c '
            .items
            | group_by(.metadata.labels["spi-stack.layer"] // "-")
            | map({
                layer: (.[0].metadata.labels["spi-stack.layer"] // "-"),
                total: length,
                ready: ([ .[]
                    | select((.status.conditions // [])[]?
                        | select(.type == "Ready" and .status == "True"))
                ] | length)
              })
            | sort_by(.layer)
        ' <<<"$ksts_json")

        ready_total=$(jq -r '[.[].ready] | add // 0' <<<"$per_layer")
        all_total=$(jq -r '[.[].total] | add // 0' <<<"$per_layer")

        while IFS=$'\t' read -r layer ready total_in_layer; do
            [ -z "$layer" ] && continue
            if [ "$ready" = "$total_in_layer" ] && [ -z "${LAYER_DONE[$layer]:-}" ]; then
                LAYER_DONE[$layer]=1
                print_banner "✓ Layer ${layer} ready (${total_in_layer}/${total_in_layer}) at $(fmt_mmss "$elapsed")"
            fi
        done < <(jq -r '.[] | [.layer, .ready, .total] | @tsv' <<<"$per_layer")

        compact=$(jq -r '
            map("L\(.layer) \(.ready)/\(.total)" + (if .ready == .total then " ✓" else "" end))
            | join(" · ")
        ' <<<"$per_layer")

        printf '[%s / %s] %s/%s Ready · %s\n' \
            "$(fmt_mmss "$elapsed")" "$(fmt_mmss "$TIMEOUT")" \
            "$ready_total" "$all_total" "$compact"

        if [ "$ready_total" = "$all_total" ] && [ "$all_total" -gt 0 ]; then
            print_banner "✓ all $all_total Kustomizations Ready at $(fmt_mmss "$elapsed")"
            dump_status
            exit 0
        fi
    fi

    if [ $(( elapsed - LAST_STATUS )) -ge "$STATUS_INTERVAL" ]; then
        echo
        echo "─── status checkpoint at $(fmt_mmss "$elapsed") ───"
        dump_status
        echo
        LAST_STATUS=$elapsed
    fi

    sleep "$HEARTBEAT"
done
