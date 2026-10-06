import unittest
from manifest_asset_metadata import distribution_metadata


class DistributionMetadataTests(unittest.TestCase):
    def test_all_helper_platforms_preserve_self_host_edition(self):
        for name in ("breeze-helper-windows.msi", "breeze-helper-macos.dmg", "breeze-helper-linux.AppImage"):
            with self.subTest(name=name):
                self.assertEqual(distribution_metadata([
                    {"name": name, "edition": "self-host", "platformTrust": "none", "sha256": "old"}
                ], name), {"edition": "self-host"})

    def test_preserves_distribution_restriction_and_hosted_edition(self):
        self.assertEqual(distribution_metadata([
            {"name": "asset", "edition": "hosted", "intendedUse": "recovery"}
        ], "asset"), {"edition": "hosted", "intendedUse": "recovery"})

    def test_rebuilt_msi_uses_build_evidence(self):
        self.assertEqual(distribution_metadata([
            {"name": "breeze-agent.msi", "edition": "hosted"}
        ], "breeze-agent.msi", built_msi_edition="self-host"), {"edition": "self-host"})

    def test_legacy_msi_does_not_invent_edition(self):
        self.assertEqual(distribution_metadata([
            {"name": "breeze-agent.msi"}
        ], "breeze-agent.msi", built_msi_edition="legacy"), {})

    def test_rejects_missing_duplicate_invalid_and_signing_input(self):
        for assets in ([], [{"name": "asset"}, {"name": "asset"}],
                       [{"name": "asset", "edition": "bogus"}],
                       [{"name": "asset", "intendedUse": "signing-input"}]):
            with self.subTest(assets=assets), self.assertRaises(ValueError):
                distribution_metadata(assets, "asset")

    def test_legacy_build_cannot_claim_modern_edition(self):
        with self.assertRaisesRegex(ValueError, "legacy MSI"):
            distribution_metadata([{"name": "breeze-agent.msi", "edition": "self-host"}],
                                  "breeze-agent.msi", built_msi_edition="legacy")


if __name__ == "__main__":
    unittest.main()
