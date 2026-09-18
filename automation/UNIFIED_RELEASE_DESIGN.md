# Unified Breeze release design

## Objective

Treat one upstream Breeze version as one immutable SwiftyBits release unit:

- verified official source commit;
- digest-pinned API, web, portal, binaries, and supported executor images;
- organization-signed Windows and macOS installers;
- mirrored Linux and helper artifacts;
- version-matched add-on overlays, when an upstream hook is not available; and
- a signed release manifest describing the complete unit.

The same release manifest is promoted, without rebuilding, through Dev, UAT,
and Production.

## Pipeline

1. The scheduled detector finds a new official Breeze release.
2. The signing approval gate verifies the official Ed25519 manifest and binds
   the movable Git tag to its signed source commit.
3. Platform jobs sign the installer artifacts.
4. Any temporary API or web overlay is built from that exact source commit,
   tested, pushed by digest, and recorded in the release contract.
5. The SwiftyBits manifest records both the signed artifacts and the verified
   core image inventory, then is signed with the SwiftyBits manifest key.
6. Dev receives the release automatically after a configuration backup, a
   database backup, and a recursive ZFS snapshot.
7. Dev validation checks migrations, every first-party container digest,
   public health, login, agent check-in, ticket creation, AI streaming, and
   integration containment.
8. The exact Dev-approved manifest waits at the UAT environment gate. UAT runs
   the same checks against its own data, URLs, ports, and secrets.
9. The exact UAT-approved manifest waits at the Production environment gate.
10. Production is promoted during its change window and observed before the
    previous rollback bundle expires.

If approval happens after detection, the waiting run continues immediately;
it does not wait for the next six-hour detector cycle.

## Release contract

Every release manifest must contain:

- `release` and `sourceCommit`;
- the signed installer and mirrored artifact hashes;
- the official image repository and digest for `api`, `web`, `portal`, and
  `binaries`;
- any enabled executor image digests;
- any SwiftyBits overlay image digests; and
- the required Compose/environment schema revision.

Promotion refuses mutable tags, an unsigned manifest, source-commit mismatch,
missing image entries, digest drift, or a release assembled from different
versions.

## Add-on boundary

Preferred order:

1. Out-of-process sidecar or service using supported Breeze APIs.
2. Breeze extension/plugin using a supported extension contract.
3. Small version-matched overlay built automatically from the exact upstream
   source commit.
4. Permanent core fork only as a last resort.

Vendor Hub already follows the sidecar model for data, credentials, polling,
and webhooks. Its current navigation page is a temporary web overlay.

BookCentral currently depends on a temporary API overlay that provides
`POST /integrations/tickets`. That route must either ship upstream or be built
and signed automatically for each Breeze release before a full-stack promotion
can proceed.

No promotion may silently replace a custom API or web image with stock if that
would remove an active capability.

## Automatic versus approval-required

Automatic:

- release detection and cryptographic verification;
- installer signing after the signing approval;
- image and artifact manifest creation;
- backups and snapshots;
- Dev deployment and machine-verifiable checks; and
- digest-parity and version-parity checks.

Approval-required:

- signing credentials use;
- UAT promotion;
- Production promotion; and
- a breaking configuration or database preflight identified by `UPGRADING.md`.

Routine releases therefore remain one process. A release that introduces a new
required secret, destructive migration, manual consent step, or Compose service
cannot be safely zero-touch; it stops before Dev with the exact required action.

## Version display

The API environment values `APP_VERSION`, `BREEZE_VERSION`, and
`BINARY_VERSION`, the API health response, the first-party container digests,
and the release manifest must all agree. TrueNAS custom-app metadata should be
generated from the same version so its UI does not continue displaying a stale
static value.

## Current cutover gate

The existing v0.114.0 signed release predates the complete image-inventory
contract and remains immutable. All three environments still use the temporary
BookCentral API overlay; Dev also uses the Vendor Hub web overlay. Do not perform
the stock-core cutover until those two capabilities have version-matched release
artifacts or their upstream replacements are available.
