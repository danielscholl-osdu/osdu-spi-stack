#!/usr/bin/env bash
#
# Orphan resource group sweeper.
#
# Reaps Azure resource groups that were provisioned by spi-stack CI but
# outlived their pipeline. A canceled smoke pipeline kills the teardown
# job along with every other job, so `if: always()` does not save us;
# this sweeper is the backstop.
#
# Selection rules (ALL must hold):
#   1. Resource group name starts with $SWEEP_NAME_PREFIX (default
#      "spi-stack-ci-")
#   2. Resource group carries tag spi-ci-sweep-eligible=true
#   3. Resource group carries tag spi-created-utc with an ISO-8601
#      timestamp older than $SWEEP_AGE_HOURS (default 3)
#
# The name-prefix gate is a second line of defense so the sweeper cannot
# reap a production environment that accidentally inherited the tag.
#
# Environment variables:
#   SWEEP_NAME_PREFIX  resource group name prefix to match (default "spi-stack-ci-")
#   SWEEP_AGE_HOURS    minimum age in hours before a group is eligible (default 3)
#   SWEEPER_DRY_RUN    "true" lists candidates without deleting (default "false")
#
# Exits 0 on success regardless of how many groups were reaped. A broken
# tag on one group logs and continues rather than failing the whole run.

set -euo pipefail

: "${SWEEP_NAME_PREFIX:=spi-stack-ci-}"
: "${SWEEP_AGE_HOURS:=3}"
: "${SWEEPER_DRY_RUN:=false}"

now_epoch=$(date -u +%s)
age_threshold_sec=$((SWEEP_AGE_HOURS * 3600))

echo "=== spi orphan RG sweeper ==="
echo "  prefix:        ${SWEEP_NAME_PREFIX}"
echo "  age_threshold: ${SWEEP_AGE_HOURS}h"
echo "  dry_run:       ${SWEEPER_DRY_RUN}"
echo "  subscription:  $(az account show --query name -o tsv)"
echo

candidates=$(az group list --tag spi-ci-sweep-eligible=true --output json)
total=$(echo "${candidates}" | jq 'length')
echo "Candidates (tagged spi-ci-sweep-eligible=true): ${total}"
echo

reaped=0
while IFS=$'\t' read -r name created; do
  [[ -z "${name}" ]] && continue

  case "${name}" in
    "${SWEEP_NAME_PREFIX}"*) ;;
    *)
      echo "  skip (prefix mismatch): ${name}"
      continue
      ;;
  esac

  if [[ -z "${created}" ]]; then
    echo "  skip (no spi-created-utc tag): ${name}"
    continue
  fi

  # Parse ISO-8601 under either GNU date or BSD date (local dev on macOS).
  if created_epoch=$(date -u -d "${created}" +%s 2>/dev/null); then
    :
  elif created_epoch=$(date -u -jf "%Y-%m-%dT%H:%M:%SZ" "${created}" +%s 2>/dev/null); then
    :
  else
    echo "  skip (cannot parse spi-created-utc='${created}'): ${name}"
    continue
  fi

  age=$((now_epoch - created_epoch))
  age_hours=$((age / 3600))

  if (( age < age_threshold_sec )); then
    echo "  skip (age ${age_hours}h < ${SWEEP_AGE_HOURS}h): ${name}"
    continue
  fi

  if [[ "${SWEEPER_DRY_RUN}" == "true" ]]; then
    echo "  DRY RUN would delete (age ${age_hours}h): ${name}"
  else
    echo "  DELETE (age ${age_hours}h): ${name}"
    az group delete --name "${name}" --yes --no-wait
    reaped=$((reaped + 1))
  fi
done < <(echo "${candidates}" | jq -r '.[] | "\(.name)\t\(.tags["spi-created-utc"] // "")"')

echo
if [[ "${SWEEPER_DRY_RUN}" == "true" ]]; then
  echo "Sweeper complete (dry run); no groups were deleted."
else
  echo "Sweeper complete; ${reaped} delete request(s) accepted (async)."
fi
