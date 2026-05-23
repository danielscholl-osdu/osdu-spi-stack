#!/usr/bin/env bash
# Capture diagnostics from a live cluster into diagnostics/<label>/.
#
# Used by CI smoke-test jobs to collect state at the end of a run so a
# human reviewing a failed pipeline can distinguish "real failure" from
# "slow but fine" from "broken component X". Every command is best-effort
# and tolerates missing kubectl context or tool absence so this script
# never fails the calling job.
#
# Usage: bash scripts/capture_diagnostics.sh <label>

set -u

LABEL="${1:-unlabeled-$(date +%s)}"
OUT="diagnostics/$LABEL"
mkdir -p "$OUT"

echo "Capturing diagnostics to $OUT"

{
    if command -v uv >/dev/null 2>&1; then
        uv run spi status 2>&1 || echo "(spi status failed)"
    else
        echo "(uv not available)"
    fi
} > "$OUT/spi-status.txt"

if command -v kubectl >/dev/null 2>&1; then
    kubectl get kustomizations -A -o yaml > "$OUT/kustomizations.yaml" 2>&1 || true
    kubectl get helmreleases -A -o yaml > "$OUT/helmreleases.yaml" 2>&1 || true
    kubectl get events -A --sort-by=.lastTimestamp 2>&1 | tail -200 > "$OUT/events.txt" || true
    kubectl get pods -A -o wide > "$OUT/pods.txt" 2>&1 || true
    kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded \
        -o wide > "$OUT/pods-not-healthy.txt" 2>&1 || true
    kubectl get nodes -o wide > "$OUT/nodes.txt" 2>&1 || true
else
    echo "(kubectl not available)" > "$OUT/no-kubectl"
fi

echo "Diagnostics written:"
ls -la "$OUT"
