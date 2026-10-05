import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('promotion', Path(__file__).with_name('promote-full-release.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ReleaseContractTests(unittest.TestCase):
    def manifest(self):
        return {'schemaVersion': 1, 'release': 'v0.121.0', 'repository': p.SIGNED_REPO, 'sourceCommit': 'a' * 40,
                'images': [{'name': n, 'repository': 'ghcr.io/lanternops/breeze/' + n,
                            'digest': 'sha256:' + 'b' * 64} for n in ('api', 'web', 'portal', 'binaries')]}

    def test_missing_component_blocks_release(self):
        m = self.manifest()
        m['images'].pop()
        with self.assertRaises(ValueError): p.image_inventory(m, '0.121.0')

    def test_repository_substitution_blocks_release(self):
        m = self.manifest()
        m['images'][0]['repository'] = 'ghcr.io/untrusted/api'
        with self.assertRaises(ValueError): p.image_inventory(m, '0.121.0')

    def test_older_release_cannot_replace_newer_component(self):
        with self.assertRaises(ValueError):
            p.check_no_downgrade({'APP_VERSION': '0.122.0', 'BINARY_VERSION': '0.121.0'}, '0.121.0')

    def test_reconciliation_updates_images_when_installer_already_current(self):
        current = {'services': {n: {'image': 'old'} for n in ('api', 'web', 'portal', 'binaries-init')}}
        env = {'APP_VERSION': '0.113.0', 'BREEZE_VERSION': '0.113.0', 'BINARY_VERSION': '0.121.0',
               'PUBLIC_APP_URL': 'https://example.test', 'SECRET': 'preserve'}
        current['services']['api']['environment'] = env
        images = p.image_inventory(self.manifest(), '0.121.0')
        desired = p.desired_config(current, '0.121.0', images, {})
        self.assertEqual(desired['services']['api']['environment']['APP_VERSION'], '0.121.0')
        self.assertEqual(desired['services']['web']['image'], images['web'])
        self.assertEqual(desired['services']['api']['environment']['SECRET'], 'preserve')
        self.assertEqual(env['APP_VERSION'], '0.113.0')
        self.assertEqual(desired['services']['api']['environment']['PUBLIC_WEB_URL'], 'https://example.test')

    def test_signature_rejects_modified_manifest(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        key = Ed25519PrivateKey.generate()
        public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        signature = base64.b64encode(key.sign(b'original'))
        p.verify_manifest(b'original', signature, public)
        with self.assertRaises(ValueError): p.verify_manifest(b'modified', signature, public)


if __name__ == '__main__': unittest.main()
