# Unified Breeze release design

The implemented host and workflow behavior is documented in README.md. This
release unit combines verified upstream API, web, portal, and binaries images
with organization-signed installer assets from the same source commit.

Temporary customizations are reproducible root-owned overlays: BookCentral
scoped ticket intake, Dev Vendor Hub navigation, and AI streaming startup timeout.
The binary initializer also embeds the release's verified signed Windows MSI;
API GitHub-mode metadata synchronization alone does not replace local stock MSI
bytes. Automatic binary promotion advances downloads and update offers at each
release, rather than leaving an older promoted catalog version in place.
They are rebuilt from the signed image inventory or exact manifest source commit,
with content-derived tags and provenance checks, rather than retaining old core
images. Overlay source changes belong in this repository. Future upstream changes
that invalidate an overlay stop the release before application mutation.

One signed release advances through Dev, UAT, and Production only after each
stage passes actual image and version verification. Detection independently
reconciles already signed releases, so publishing successfully no longer hides a
failed application promotion. Superseded releases are rejected; concurrent
release trains are serialized. Signing credentials remain behind the signing
environment; application stages automatically progress after checks.

Actual PostgreSQL dumps and API-data archives cover named-volume state. Recovery
must account for forward migrations and intervening production writes; the train
does not automatically rewind a live database. Protected host settings retain
environment-specific URLs, secrets, ports, and storage. Those settings are never
published in this repository.

Release verification covers manifest authenticity, all listed asset hashes and
sizes, enabled first-party image IDs, service health, API and baked web versions,
local binary version/access, and public web/Quick Support/portal reachability.
It also verifies the promoted Windows download redirect and hashes the actual
public MSI response against the signed release manifest. Prepared images use a
local Compose pull policy after verified pulls/builds, including the initializer.
BookCentral authorization and error paths are exercised against the actual
upstream bundle during overlay build. These are machine checks, not a claim that
all tenant-specific integrations or device operating systems have been manually
exercised. A required secret or incompatible schema/customization must fail
closed and surface the failed stage rather than silently claim success.
