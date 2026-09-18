#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly SIGNED_REPOSITORY="VincentSwiftyBits/breeze-selfhost-signing"
readonly BACKUP_ROOT="/mnt/SwiftyBits/Apps/Breeze_RMM_MSP/Automation/backups"
readonly LOCK_FILE="/run/lock/breeze-signed-release-promotion.lock"
readonly APP_UPDATE_HELPER="/mnt/SwiftyBits/Apps/Breeze_RMM_MSP/Automation/bin/app-update-from-file.py"

(( EUID == 0 )) || {
  echo "promotion must run through the approved root wrapper" >&2
  exit 77
}

as_root() { command "$@"; }

usage() {
  echo "usage: $0 <dev|uat|production> <X.Y.Z>" >&2
  exit 64
}

[[ $# -eq 2 ]] || usage
environment="$1"
version="$2"

if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$ ]]; then
  echo "invalid Breeze version: $version" >&2
  exit 64
fi

case "$environment" in
  dev)
    app="breeze-rmm-dev"
    dataset="SwiftyBits/Apps/Breeze_RMM_MSP/BreezeRMM_Dev"
    health_url="https://stsmsp-dev.swiftybits.com/health"
    ;;
  uat)
    app="breeze-rmm-uat"
    dataset="SwiftyBits/Apps/Breeze_RMM_MSP/BreezeRMM_UAT"
    health_url="https://stsmsp-uat.swiftybits.com/health"
    ;;
  production)
    app="breeze-rmm"
    dataset="SwiftyBits/Apps/Breeze_RMM_MSP/BreezeRMM_Prod"
    health_url="https://stsmsp.swiftybits.com/health"
    ;;
  *) usage ;;
esac

for command in curl flock jq midclt zfs docker python3; do
  command -v "$command" >/dev/null || {
    echo "required command is unavailable: $command" >&2
    exit 69
  }
done

exec 9>"$LOCK_FILE"
flock -n 9 || {
  echo "another Breeze promotion is already running" >&2
  exit 75
}

release_json="$(curl --fail --silent --show-error --location \
  --proto '=https' --tlsv1.2 \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  "https://api.github.com/repos/${SIGNED_REPOSITORY}/releases/tags/v${version}")"

jq -e --arg tag "v${version}" '
  .tag_name == $tag and
  .draft == false and
  .prerelease == false and
  ([.assets[].name] | contains([
    "breeze-agent.msi",
    "breeze-agent-windows-amd64.exe",
    "checksums.txt",
    "release-artifact-manifest.json",
    "release-artifact-manifest.json.ed25519"
  ]))
' <<<"$release_json" >/dev/null || {
  echo "signed release v${version} is missing or incomplete" >&2
  exit 65
}

config="$(as_root midclt call app.config "$app")"
current="$(jq -er '
  .services.api.environment as $env |
  if ($env | type) == "array" then
    ($env[] | select(startswith("BINARY_VERSION=")) | split("=")[1])
  else
    $env.BINARY_VERSION
  end
' <<<"$config")"

if [[ "$current" == "$version" ]]; then
  echo "${app} already targets signed installer v${version}; verifying only"
else
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_dir="${BACKUP_ROOT}/${app}"
  as_root install -d -m 0700 "$backup_dir"
  printf '%s\n' "$config" | as_root tee \
    "${backup_dir}/${timestamp}-before-v${version}.json" >/dev/null

  snapshot="${dataset}@pre-signed-v${version}-${timestamp}"
  as_root zfs snapshot -r "$snapshot"
  echo "created rollback snapshot ${snapshot}"

  updated="$(jq --arg version "$version" '
    .services.api.environment |=
      if type == "array" then
        map(if startswith("BINARY_VERSION=") then "BINARY_VERSION=" + $version else . end)
      elif type == "object" then
        .BINARY_VERSION = $version
      else
        error("api.environment must be an array or object")
      end
  ' <<<"$config")"

  payload="$(jq -c '{custom_compose_config:.}' <<<"$updated")"
  payload_file="$(mktemp /run/breeze-app-update.XXXXXX.json)"
  trap 'rm -f "${payload_file:-}"' EXIT
  printf '%s\n' "$payload" >"$payload_file"
  chmod 0600 "$payload_file"
  job_id="$(as_root python3 "$APP_UPDATE_HELPER" "$app" "$payload_file")"
  rm -f "$payload_file"
  payload_file=""
  [[ "$job_id" =~ ^[0-9]+$ ]] || {
    echo "TrueNAS did not return an app.update job id" >&2
    exit 70
  }

  job_deadline=$((SECONDS + 600))
  while (( SECONDS < job_deadline )); do
    job="$(as_root midclt call core.get_jobs "[[\"id\",\"=\",${job_id}]]")"
    job_state="$(jq -r '.[0].state // empty' <<<"$job")"
    case "$job_state" in
      SUCCESS) break ;;
      FAILED|ABORTED)
        job_error="$(jq -r '.[0].error // "unknown TrueNAS app.update error"' <<<"$job")"
        echo "TrueNAS app.update job ${job_id} ${job_state}: ${job_error}" >&2
        exit 70
        ;;
    esac
    sleep 5
  done
  [[ "${job_state:-}" == "SUCCESS" ]] || {
    echo "TrueNAS app.update job ${job_id} did not finish within 10 minutes" >&2
    exit 70
  }
fi

deadline=$((SECONDS + 600))
while (( SECONDS < deadline )); do
  state="$(as_root midclt call app.query | jq -r --arg app "$app" \
    '.[] | select(.name == $app) | .state')"
  if [[ "$state" == "RUNNING" ]]; then
    container="ix-${app}-api-1"
    container_version="$(as_root docker exec "$container" sh -lc 'printf %s "$BINARY_VERSION"' 2>/dev/null || true)"
    health="$(curl --fail --silent --show-error --location --max-time 15 "$health_url" 2>/dev/null || true)"
    health_status="$(jq -r '.status // empty' <<<"$health" 2>/dev/null || true)"
    if [[ "$container_version" == "$version" && "$health_status" == "ok" ]]; then
      api_version="$(jq -r '.version // "unknown"' <<<"$health")"
      echo "promotion verified: environment=${environment} signed-installer=${version} api=${api_version} health=ok"
      exit 0
    fi
  fi
  sleep 10
done

echo "promotion did not verify within 10 minutes: environment=${environment} version=${version}" >&2
exit 70

