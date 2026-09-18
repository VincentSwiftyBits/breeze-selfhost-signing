# Breeze release promotion

The target release unit is the complete Breeze version: signed installer
artifacts plus the official API, web, portal, and binaries image digests from
the same verified upstream release manifest. The GitHub workflow promotes that
immutable release through Dev, UAT, and Production. Dev runs automatically.
The `breeze-uat` and `breeze-production` GitHub environments provide the
approval gates.

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
configuration, creates a recursive ZFS rollback snapshot, applies the release
contract, waits for the TrueNAS update job, and verifies the live version,
image parity, and the environment's public health endpoint.

Newly published signed manifests include the verified upstream image inventory,
so one release version can drive the installer and core application rollout.
Releases created before this contract was added need the separately verified
official manifest as a compatibility source.

## Customization gate

Do not replace a non-official API or web image automatically. A custom core
image means functionality is still patched into Breeze rather than delivered
as a sidecar, extension, or upstream feature. Promotion must stop at Dev until
that capability has either moved out of process or has a version-matched,
signed overlay image in the release contract.

The current temporary exceptions are the BookCentral ticket-intake API patch
and the small Vendor Hub navigation overlay. The Vendor Hub service itself is
already out of process and does not need rebuilding for each Breeze release.
