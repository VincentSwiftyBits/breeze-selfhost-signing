"""Runtime promotion gates: prevent a healthy old stack passing a new release."""
import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('runtime_promotion', Path(__file__).with_name('promote-full-release.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ReconciliationTests(unittest.TestCase):
    def test_missing_api_container_backup_resolves_preserved_named_volume(self):
        config = {'services': {'api': {'volumes': ['api_data:/data']}}, 'volumes': {'api_data': {}}}
        with patch.object(p, 'docker_json', side_effect=[subprocess.CalledProcessError(1, ['docker']),
                                                        [{'Mountpoint': '/docker/volumes/data/_data'}]]) as docker:
            self.assertEqual(p.api_data_source('test', config), '/docker/volumes/data/_data')
            self.assertEqual(docker.call_args.args, ('volume', 'inspect', 'ix-test_api_data'))

    def test_api_backup_requires_persistent_data(self):
        with patch.object(p, 'docker_json', return_value=[{'Mounts': []}]):
            with self.assertRaisesRegex(ValueError, 'Persistent API data'):
                p.api_data_source('test', {})

    def test_current_healthy_release_does_not_restart(self):
        with patch.object(p, 'verify') as verify:
            self.assertFalse(p.needs_update({}, {}, 'test', '0.121.0', {}, {}, {}))
            verify.assert_called_once()

    def test_saved_config_with_failed_runtime_is_repaired(self):
        with patch.object(p, 'verify', side_effect=ValueError('web never started')):
            self.assertTrue(p.needs_update({}, {}, 'test', '0.121.0', {}, {}, {}))

    def test_old_configuration_requires_update(self):
        with patch.object(p, 'verify') as verify:
            self.assertTrue(p.needs_update({'old': True}, {}, 'test', '0.121.0', {}, {}, {}))
            verify.assert_not_called()


class RuntimeVerificationTests(unittest.TestCase):
    def setUp(self):
        self.images = {name: 'example/' + name + '@sha256:' + 'a' * 64
                       for name in ('api', 'web', 'portal', 'binaries')}
        self.containers = {service: {'Image': 'sha256:' + name,
                                    'State': {'Health': {'Status': 'healthy'}}}
                           for service, name in [('api', 'api'), ('web', 'web'),
                                                 ('portal', 'portal'), ('binaries-init', 'binaries')]}
        self.containers['binaries-init']['State'] = {'Status': 'exited', 'ExitCode': 0}
        self.health = {'status': 'ok', 'version': '0.121.0'}

    def docker(self, *args):
        if args[0] == 'image':
            name = args[-1].split('/')[1].split('@')[0]
            return [{'Id': 'sha256:' + name}]
        service = args[-1].removeprefix('ix-test-').removesuffix('-1')
        return [self.containers[service]]

    def fetch(self, url):
        return json.dumps(self.health).encode() if url.endswith('/health') else b'page'

    def verify(self):
        with patch.object(p, 'docker_json', side_effect=self.docker), \
             patch.object(p, 'fetch', side_effect=self.fetch), \
             patch.object(p, 'run') as run, \
             patch.object(p.subprocess, 'check_output', return_value='0.121.0\n'):
            p.verify('test', '0.121.0', self.images, {'url': 'https://example.test'})
            return run

    def test_complete_current_stack_passes(self):
        self.assertTrue(self.verify().called)

    def test_public_outage_does_not_redeploy_healthy_current_stack(self):
        with patch.object(p, 'docker_json', side_effect=self.docker), \
             patch.object(p, 'fetch', side_effect=p.urllib.error.URLError('public outage')) as fetch, \
             patch.object(p, 'run'), \
             patch.object(p.subprocess, 'check_output', return_value='0.121.0\n'):
            self.assertFalse(p.needs_update({}, {}, 'test', '0.121.0', self.images,
                                           {'url': 'https://example.test'}, None))
            fetch.assert_not_called()

    def test_old_api_health_fails_even_if_healthy(self):
        self.health['version'] = '0.113.0'
        with self.assertRaisesRegex(ValueError, 'health/version'):
            self.verify()

    def test_wrong_web_image_fails_even_if_healthy(self):
        self.containers['web']['Image'] = 'sha256:old-web'
        with self.assertRaisesRegex(ValueError, 'Running image'):
            self.verify()

    def test_failed_binary_init_fails(self):
        self.containers['binaries-init']['State']['ExitCode'] = 1
        with self.assertRaisesRegex(ValueError, 'initialization'):
            self.verify()

    def test_unhealthy_portal_fails(self):
        self.containers['portal']['State']['Health']['Status'] = 'unhealthy'
        with self.assertRaisesRegex(ValueError, 'healthy: portal'):
            self.verify()

    def test_old_binary_volume_fails(self):
        with patch.object(p, 'docker_json', side_effect=self.docker), \
             patch.object(p, 'fetch', side_effect=self.fetch), patch.object(p, 'run'), \
             patch.object(p.subprocess, 'check_output', return_value='0.113.0\n'):
            with self.assertRaisesRegex(ValueError, 'volume version'):
                p.verify('test', '0.121.0', self.images, {'url': 'https://example.test'})

    def test_web_baked_version_failure_propagates(self):
        with patch.object(p, 'docker_json', side_effect=self.docker), \
             patch.object(p, 'fetch', side_effect=self.fetch), \
             patch.object(p, 'run', side_effect=subprocess.CalledProcessError(1, ['node'])):
            with self.assertRaises(subprocess.CalledProcessError):
                p.verify('test', '0.121.0', self.images, {'url': 'https://example.test'})


class MiddlewareJobTests(unittest.TestCase):
    def test_success_waits_for_terminal_job(self):
        client = Mock()
        client.call.side_effect = [42, [{'state': 'RUNNING'}], [{'state': 'SUCCESS'}]]
        with patch.object(p.time, 'sleep'):
            p.app_update(client, 'test', {'services': {}})
        self.assertEqual(client.call.call_count, 3)

    def test_failure_does_not_expose_compose_secrets(self):
        client = Mock()
        client.call.side_effect = [42, [{'state': 'FAILED', 'error': 'password=secret'}]]
        with self.assertRaises(RuntimeError) as error:
            p.app_update(client, 'test', {'services': {}})
        self.assertNotIn('secret', str(error.exception))


class ConfigurationPreservationTests(unittest.TestCase):
    def test_preserves_ports_volumes_secrets_sidecars_and_original(self):
        config = {'services': {n: {'image': 'old', 'volumes': ['/persistent:/data']}
                              for n in ('api', 'web', 'portal', 'binaries-init')},
                  'networks': {'private': {}}, 'volumes': {'persistent': {}}}
        config['services']['api'].update(environment={'PUBLIC_APP_URL': 'https://example.test',
                                                     'BINARY_VERSION': '0.121.0', 'SECRET': 'keep'},
                                         ports=['10100:3001'], group_add=['1000', '1010'])
        config['services']['vendorhub'] = {'image': 'vendor-sidecar:existing', 'environment': {'TOKEN': 'keep'}}
        before = copy.deepcopy(config)
        desired = p.desired_config(config, '0.121.0', {n: 'new-' + n for n in ('api', 'web', 'portal', 'binaries')}, {})
        self.assertEqual(config, before)
        self.assertEqual(desired['services']['vendorhub'], before['services']['vendorhub'])
        for name in ('api', 'web', 'portal', 'binaries-init'):
            self.assertEqual(desired['services'][name]['volumes'], before['services'][name]['volumes'])
        self.assertEqual(desired['services']['api']['ports'], ['10100:3001'])
        self.assertEqual(desired['services']['api']['environment']['SECRET'], 'keep')
        self.assertEqual(desired['services']['api']['group_add'], ['1000', '1010'])


class ArtifactIntegrityTests(unittest.TestCase):
    names = ('breeze-agent.msi', 'breeze-agent-windows-amd64.exe', 'breeze-agent-linux-amd64')

    def fixture(self):
        content = b'authenticated artifact bytes'
        manifest = {'assets': [{'name': name, 'sha256': hashlib.sha256(content).hexdigest(),
                                'size': len(content)} for name in self.names]}
        urls = {name: 'https://example.test/' + name for name in self.names}
        return content, manifest, urls

    def test_all_artifacts_verified_and_cached(self):
        content, manifest, urls = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with patch.object(p.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(content)) as fetch:
                p.verified_artifacts(manifest, urls, cache)
                self.assertEqual(fetch.call_count, 3)
                p.verified_artifacts(manifest, urls, cache)
                self.assertEqual(fetch.call_count, 3)
            self.assertTrue(all((cache / name).read_bytes() == content for name in self.names))

    def test_corrupted_same_size_cache_is_downloaded_again(self):
        content, manifest, urls = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            for name in self.names:
                (cache / name).write_bytes(content)
            (cache / self.names[0]).write_bytes(b'x' * len(content))
            with patch.object(p.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(content)) as fetch:
                p.verified_artifacts(manifest, urls, cache)
                self.assertEqual(fetch.call_count, 1)

    def test_download_hash_mismatch_cannot_be_promoted_to_cache(self):
        content, manifest, urls = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            with patch.object(p.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'x' * len(content))):
                with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                    p.verified_artifacts(manifest, urls, cache)
            self.assertFalse((cache / self.names[0]).exists())

    def test_oversized_or_truncated_download_rejected(self):
        content, manifest, urls = self.fixture()
        for received in (content + b'extra', content[:-1]):
            with self.subTest(size=len(received)), tempfile.TemporaryDirectory() as folder:
                with patch.object(p.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(received)):
                    with self.assertRaises(ValueError):
                        p.verified_artifacts(manifest, urls, Path(folder))
                self.assertFalse((Path(folder) / self.names[0]).exists())

    def test_required_artifacts_missing_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Required distribution'):
                p.verified_artifacts({'assets': []}, {}, Path(folder))

    def test_manifest_artifact_has_no_matching_release_asset_rejected(self):
        _, manifest, _ = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(KeyError):
                p.verified_artifacts(manifest, {}, Path(folder))

    def test_traversal_and_invalid_metadata_rejected_before_fetch(self):
        _, manifest, urls = self.fixture()
        for field, value in [('name', '../escape'), ('name', r'..\escape'),
                             ('size', 0), ('size', 2 * 1024 ** 3 + 1),
                             ('size', '25'), ('sha256', 'invalid')]:
            invalid = copy.deepcopy(manifest)
            invalid['assets'][0][field] = value
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as folder:
                with patch.object(p.urllib.request, 'urlopen') as fetch:
                    with self.assertRaises(ValueError):
                        p.verified_artifacts(invalid, urls, Path(folder))
                    fetch.assert_not_called()


class ManifestSchemaTests(unittest.TestCase):
    def test_unknown_schema_rejected(self):
        manifest = {'schemaVersion': 999, 'release': 'v0.121.0', 'repository': p.SIGNED_REPO,
                    'sourceCommit': 'a' * 40,
                    'images': [{'name': name, 'repository': 'ghcr.io/lanternops/breeze/' + name,
                                'digest': 'sha256:' + 'b' * 64}
                               for name in ('api', 'web', 'portal', 'binaries')]}
        with self.assertRaisesRegex(ValueError, '[Ss]chema'):
            p.image_inventory(manifest, '0.121.0')


if __name__ == '__main__':
    unittest.main()
