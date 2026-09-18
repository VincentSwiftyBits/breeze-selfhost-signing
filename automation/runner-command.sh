#!/usr/bin/env bash
set -euo pipefail

readonly DEPLOY_SCRIPT="/mnt/SwiftyBits/Apps/Breeze_RMM_MSP/Automation/bin/promote-signed-release"

read -r action environment version extra <<<"${SSH_ORIGINAL_COMMAND:-}"
if [[ "$action" != "promote" || -n "${extra:-}" ]]; then
  echo "unsupported automation command" >&2
  exit 64
fi

case "$environment" in
  dev|uat|production) ;;
  *) echo "invalid environment" >&2; exit 64 ;;
esac

if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]; then
  echo "invalid version" >&2
  exit 64
fi

exec sudo -n "$DEPLOY_SCRIPT" "$environment" "$version"
