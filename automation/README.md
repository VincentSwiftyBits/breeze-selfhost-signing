# Complete Breeze release promotion

The train reconciles signed releases into Dev, UAT, and Production in that order.
Detection runs every fifteen minutes and when this repository publishes a release.
New releases retain the signing environment and its credentials; already signed
releases retry deployment independently of signing. Application stages progress
automatically after verification, without deployment approval gates.

## Host installation

The root-owned host directory contains `promote-signed-release` (the shell entry
point), `promote-full-release.py`, `build-overlays.py`, and the complete `overlays/`
directory. Keep it unwritable by the runner account. The existing forced SSH
command continues accepting only `promote <dev|uat|production> <X.Y.Z>`.

Copy `release-train.example.json` to the protected host configuration directory
as `release-train.json`, using the actual environment URLs and backup directory.
Live settings and application secrets must never be committed to this repository.

## Release verification

The promoter validates the organization-signed manifest against the deployment's
trusted Ed25519 public keys. It requires a stable release and immutable API, web,
portal, and binary image digests. All artifacts listed in that manifest are
cached and verified by hash and size before application configuration changes.

Version-matched BookCentral and web overlays are built from verified base images.
Dev's Vendor Hub UI is rebuilt from the manifest's source commit. Overlay tags
include content-derived identifiers; cached image provenance must match. The
BookCentral handler authorization tests run during the image build. AI streaming
keeps its five-minute startup timeout. Unrecognized upstream structures fail
preflight rather than silently removing custom functionality.

Before a changed deployment, the promoter saves a protected Compose configuration,
a PostgreSQL custom-format dump validated by pg_restore, and an archive of the
actual mounted API data volume. These replace the old dataset-only snapshot,
which did not cover the Docker named volumes. Database recovery is manual:
rolling an application image back does not undo forward schema migrations.

Supported TrueNAS app.update applies the configuration while preserving ports,
secrets, storage, and unrelated services. Verification requires actual running
image IDs, healthy services, API and baked frontend version parity, readable
version-matched local binaries, and reachable web, Quick Support, and portal
pages. Health alone never satisfies promotion. Local group access is preserved
without making data world-readable. PUBLIC_WEB_URL follows each environment's
PUBLIC_APP_URL.

## Ordering and recovery

One GitHub deployment concurrency group serializes releases. A host lock also
serializes direct calls. Older targets are rejected when a newer signed or
installed version exists. Failed stages block later stages; subsequent detector
runs retry reconciliation. Protected recovery bundles and per-environment plans
are retained on the host. Restore database state only after reviewing migrations
and production writes; the train never silently rolls live data backward.

## Checks

Run `python -m unittest discover -s automation -p 'test_*.py'` with cryptography
installed, `node --test scripts/verify-manifest.test.mjs`, and actionlint. These
run in addition to release-time real-image overlay tests and live verification.
# OpenAI-compatible connections

Set `ai_tool_search: true` for an environment to enable SDK tool discovery. This keeps the full Breeze catalog from exceeding OpenAI's 128-tool request limit. The API overlay preserves tool-reference results across the gateway so discovery can complete its round trip. The builder tests this behavior against the actual upstream bundle before deploying a derived image and fails for an unrecognized layout.

GPT-4.1 nano is a low-cost starter compatible with the current gateway. Newer reasoning models require additional request-parameter compatibility work; a failed model verification must not be overridden by manually claiming tool support. Provider keys, model prices, and feature defaults remain partner settings, and promotions preserve them.
