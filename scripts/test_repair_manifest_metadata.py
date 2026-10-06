import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from repair_manifest_metadata import repair_manifest


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        content = b"verified helper bytes"
        self.name = "breeze-helper-windows.msi"
        (self.root / self.name).write_bytes(content)
        self.asset = {"name": self.name, "sha256": hashlib.sha256(content).hexdigest(),
                      "size": len(content), "platformTrust": "windows-authenticode-required"}
        self.current = {"schemaVersion": 1, "release": "v0.121.0", "sourceCommit": "a" * 40,
                        "repository": "example/signed", "assets": [self.asset]}
        self.official = {**copy.deepcopy(self.current), "repository": "lanternops/breeze"}
        self.official["assets"][0]["edition"] = "self-host"

    def test_metadata_only_preserves_bytes_identity_and_original(self):
        repaired = repair_manifest(self.current, self.official, self.root)
        self.assertEqual(repaired["assets"][0], {**self.asset, "edition": "self-host"})
        self.assertNotIn("edition", self.current["assets"][0])
        self.assertEqual((self.root / self.name).read_bytes(), b"verified helper bytes")

    def test_rejects_mirrored_helper_different_from_official(self):
        self.official["assets"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "mirrored Helper differs"):
            repair_manifest(self.current, self.official, self.root)

    def test_rejects_changed_published_bytes(self):
        (self.root / self.name).write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "checksum/size mismatch"):
            repair_manifest(self.current, self.official, self.root)

    def test_rejects_source_release_and_schema_mismatch(self):
        for field, value in (("sourceCommit", "b" * 40), ("release", "v0.120.0"), ("schemaVersion", 2)):
            other = copy.deepcopy(self.official)
            other[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "mismatch"):
                repair_manifest(self.current, other, self.root)

    def test_rebuilt_msi_requires_hash_bound_build_evidence(self):
        name = "breeze-agent.msi"
        (self.root / name).write_bytes(b"verified helper bytes")
        self.current["assets"][0]["name"] = name
        self.official["assets"][0]["name"] = name
        with self.assertRaisesRegex(ValueError, "edition evidence"):
            repair_manifest(self.current, self.official, self.root)
        evidence = {"edition": "self-host", "sha256": self.asset["sha256"]}
        self.assertEqual(repair_manifest(self.current, self.official, self.root, evidence)["assets"][0]["edition"], "self-host")

    def test_rejects_removing_existing_restriction(self):
        self.current["assets"][0]["intendedUse"] = "recovery"
        with self.assertRaisesRegex(ValueError, "cannot remove"):
            repair_manifest(self.current, self.official, self.root)

    def test_rejects_changing_existing_edition(self):
        self.current["assets"][0]["edition"] = "hosted"
        with self.assertRaisesRegex(ValueError, "conflicting existing edition"):
            repair_manifest(self.current, self.official, self.root)


if __name__ == "__main__":
    unittest.main()
