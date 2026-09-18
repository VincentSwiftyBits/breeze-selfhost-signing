# Breeze signed-installer promotion

The GitHub workflow promotes an already signed Breeze installer release through
Dev, UAT, and Production. Dev runs automatically. The `breeze-uat` and
`breeze-production` GitHub environments provide the approval gates.

The self-hosted runner executes `promote-breeze`, which connects through a
forced-command SSH key. `runner-command.sh` accepts only the three approved
environment names and a validated semantic version.

On TrueNAS, install the host-side files as:

- `promote-signed-release.sh` ->
  `/mnt/SwiftyBits/Apps/Breeze_RMM_MSP/Automation/bin/promote-signed-release`
- `app-update-from-file.py` ->
  `/mnt/SwiftyBits/Apps/Breeze_RMM_MSP/Automation/bin/app-update-from-file.py`
- `runner-command.sh` ->
  `/mnt/SwiftyBits/BreezeAutomationCommand/runner-command`

The Python helper deliberately sends the large custom Compose payload over the
local middleware socket. Passing the expanded configuration as a `sudo`
command-line argument can be rejected by TrueNAS command auditing.

Each promotion validates the signed GitHub release, saves the current app
configuration, creates a recursive ZFS rollback snapshot, changes only
`BINARY_VERSION`, waits for the TrueNAS update job, and verifies both the live
container value and the environment's public health endpoint.

This pipeline updates the signed installer train. It does not change the Breeze
Web/API container images; those versions are managed by the separate core
application rollout.
