#!/usr/bin/env python3
"""Reconcile a complete, verified Breeze release through supported TrueNAS API."""
import argparse
import base64
import copy
import datetime as dt
try:
    import fcntl
except ImportError:  # Pure configuration tests also run on Windows.
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

SIGNED_REPO = 'VincentSwiftyBits/breeze-selfhost-signing'
OFFICIAL_REPO = 'LanternOps/breeze'
HERE = Path(__file__).resolve().parent
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
DIGEST_RE = re.compile(r'^sha256:[a-f0-9]{64}$')


def version_tuple(version):
    if not VERSION_RE.fullmatch(version):
        raise ValueError('Only stable X.Y.Z releases are accepted')
    return tuple(map(int, version.split('.')))


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def docker_json(*args):
    return json.loads(subprocess.check_output(['docker', *args]))


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Breeze-full-release-train'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verified_artifacts(manifest, assets, cache):
    names = set()
    for artifact in manifest['assets']:
        name, wanted, size = artifact['name'], artifact['sha256'], artifact['size']
        if name in names or Path(name).name != name or '/' in name or '\\' in name or name in ('.', '..'):
            raise ValueError('Invalid or duplicate artifact name')
        names.add(name)
        if not re.fullmatch('[a-f0-9]{64}', wanted) or not isinstance(size, int) or not 0 < size <= 2 * 1024 ** 3:
            raise ValueError('Invalid artifact integrity metadata')
        path = cache / name
        valid = path.exists() and path.stat().st_size == size and hash_file(path) == wanted
        if not valid:
            req = urllib.request.Request(assets[name], headers={'User-Agent': 'Breeze-full-release-train'})
            temporary = path.with_name(path.name + '.download')
            with urllib.request.urlopen(req, timeout=60) as response, temporary.open('wb') as output:
                count = 0
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > size:
                        raise ValueError('Artifact exceeds manifest size')
                    output.write(block)
            if temporary.stat().st_size != size or hash_file(temporary) != wanted:
                raise ValueError('Signed artifact integrity mismatch: ' + name)
            temporary.replace(path)
    if not {'breeze-agent.msi', 'breeze-agent-windows-amd64.exe', 'breeze-agent-linux-amd64'} <= names:
        raise ValueError('Required distribution artifacts missing')
    print('Verified release artifacts:', len(names), flush=True)


def release(repository, version=None):
    suffix = 'latest' if version is None else 'tags/v' + version
    return json.loads(fetch(f'https://api.github.com/repos/{repository}/releases/{suffix}'))


def verify_manifest(raw, signature, keys):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    sig = base64.b64decode(signature.strip(), validate=True)
    for text in keys.split(','):
        key_bytes = base64.b64decode(text.strip(), validate=True)
        key = Ed25519PublicKey.from_public_bytes(key_bytes) if len(key_bytes) == 32 else load_der_public_key(key_bytes)
        try:
            key.verify(sig, raw)
            return
        except Exception:
            continue
    raise ValueError('Release manifest signature did not match configured trust keys')


def image_inventory(manifest, version):
    if manifest.get('schemaVersion') != 1:
        raise ValueError('Unsupported release manifest schema')
    if manifest.get('release') != 'v' + version or manifest.get('repository') != SIGNED_REPO:
        raise ValueError('Signed manifest repository/release mismatch')
    if not re.fullmatch('[a-f0-9]{40}', manifest.get('sourceCommit', '')):
        raise ValueError('Invalid source commit')
    images = {}
    for item in manifest.get('images', []):
        name = item['name']
        expected = 'ghcr.io/lanternops/breeze/' + name
        if item['repository'].lower() != expected or not DIGEST_RE.fullmatch(item['digest']):
            raise ValueError('Unexpected image repository or digest')
        if name in images:
            raise ValueError('Duplicate image entry')
        images[name] = expected + '@' + item['digest']
    if not {'api', 'web', 'portal', 'binaries'} <= images.keys():
        raise ValueError('Incomplete application image inventory')
    return images


def check_no_downgrade(env, target):
    target_tuple = version_tuple(target)
    for key in ('APP_VERSION', 'BREEZE_VERSION', 'BINARY_VERSION'):
        if env.get(key) and version_tuple(env[key]) > target_tuple:
            raise ValueError('Refusing older release than deployed ' + key)


def desired_config(current, version, images, settings):
    result = copy.deepcopy(current)
    api = result['services']['api']
    env = api['environment']
    if not isinstance(env, dict):
        raise ValueError('API environment must be a mapping')
    check_no_downgrade(env, version)
    for service, image_name in [('api', 'api'), ('web', 'web'), ('portal', 'portal'), ('binaries-init', 'binaries')]:
        result['services'][service]['image'] = images[image_name]
    for service in result['services']:
        if service in images and service not in {'api', 'web', 'portal', 'binaries'}:
            result['services'][service]['image'] = images[service]
    for key in ('APP_VERSION', 'BREEZE_VERSION', 'BINARY_VERSION'):
        env[key] = version
    public_url = settings.get('url', env['PUBLIC_APP_URL']).rstrip('/')
    env['PUBLIC_APP_URL'] = public_url
    env['PUBLIC_WEB_URL'] = public_url
    # Schema migrations precede API readiness and can exceed ordinary request health windows.
    api.setdefault('healthcheck', {})['start_period'] = '30m'
    # Existing persistent volumes use group 1000; add access without widening modes.
    groups = api.setdefault('group_add', [])
    if '1000' not in [str(x) for x in groups]:
        groups.append('1000')
    notes = result.get('x-notes')
    if isinstance(notes, str):
        result['x-notes'] = re.sub(r'(Breeze version:\*\*\s*`)[^`]+(`)', r'\g<1>' + version + r'\2', notes)
    return result


def app_update(client, app, config):
    job_id = client.call('app.update', app, {'custom_compose_config': config})
    print('TrueNAS update job', job_id, flush=True)
    deadline = time.monotonic() + 2400
    while time.monotonic() < deadline:
        job = client.call('core.get_jobs', [['id', '=', job_id]])[0]
        if job['state'] == 'SUCCESS':
            return
        if job['state'] in {'FAILED', 'ABORTED'}:
            # Raw middleware errors can embed Compose secrets: do not print them.
            raise RuntimeError(f'TrueNAS job {job_id} {job["state"]}; inspect protected host logs')
        time.sleep(5)
    raise TimeoutError(f'TrueNAS job {job_id} did not complete in 40 minutes')


def api_data_source(app, current):
    try:
        mounts = docker_json('inspect', f'ix-{app}-api-1')[0]['Mounts']
        for mount in mounts:
            if mount['Destination'] == '/data':
                return mount['Source']
    except subprocess.CalledProcessError:
        # A failed Compose update can remove a container while retaining its volume.
        for mount in current['services']['api'].get('volumes', []):
            if isinstance(mount, str):
                parts = mount.split(':')
                source, target = parts[:2] if len(parts) >= 2 else ('', '')
            else:
                source, target = mount.get('source', ''), mount.get('target', '')
            if target != '/data':
                continue
            if source.startswith('/'):
                return source
            definition = current.get('volumes', {}).get(source) or {}
            name = definition.get('name') or (source if definition.get('external') else f'ix-{app}_{source}')
            return docker_json('volume', 'inspect', name)[0]['Mountpoint']
    raise ValueError('Persistent API data volume could not be resolved for backup')


def backup(app, current, root):
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = root / app / ('full-' + stamp)
    folder.mkdir(parents=True, mode=0o700)
    (folder / 'config.json').write_text(json.dumps(current))
    with (folder / 'database.dump').open('wb') as output:
        run(['docker', 'exec', f'ix-{app}-postgres-1', 'pg_dump', '-Fc', '-U', 'breeze', '-d', 'breeze'], stdout=output)
    with (folder / 'database.dump').open('rb') as archive:
        run(['docker', 'exec', '-i', f'ix-{app}-postgres-1', 'pg_restore', '--list'], stdin=archive, stdout=subprocess.DEVNULL)
    if (folder / 'database.dump').stat().st_size < 100:
        raise ValueError('Database backup is unexpectedly empty')
    data_source = api_data_source(app, current)
    with (folder / 'api-data.tar').open('wb') as output:
        run(['tar', '--acls', '--xattrs', '--numeric-owner', '-C', data_source, '-cf', '-', '.'], stdout=output)
    checksums = '\n'.join(hash_file(path) + '  ' + path.name for path in folder.iterdir() if path.is_file())
    (folder / 'SHA256SUMS').write_text(checksums + '\n')
    print('Recovery bundle', folder, flush=True)
    return folder


def prepare_images(images, manifest, version, settings):
    for image in images.values():
        run(['docker', 'pull', image], stdout=subprocess.DEVNULL)
    result = dict(images)
    # Trusted host builder derives overlays from signed base digests and tracked patches.
    builder = HERE / 'build-overlays.py'
    if not builder.exists():
        raise ValueError('Version-matched customization builder is missing')
    payload = {'version': version, 'sourceCommit': manifest['sourceCommit'], 'images': images,
               'vendorhub': settings.get('vendorhub', False)}
    completed = run(['python3', str(builder)], input=json.dumps(payload).encode(), stdout=subprocess.PIPE)
    overlays = json.loads(completed.stdout)
    result.update(overlays['images'])
    return result, overlays


def verify(app, version, images, settings, expected_ids=None, *, local_only=False):
    prefix = 'ix-' + app + '-'
    if expected_ids is None:
        services = {'api': 'api', 'web': 'web', 'portal': 'portal', 'binaries-init': 'binaries'}
        services.update({name: name for name in images if name not in {'api', 'web', 'portal', 'binaries'}})
        expected_ids = {s: docker_json('image', 'inspect', images[n])[0]['Id'] for s, n in services.items()}
    for service, expected_id in expected_ids.items():
        container = docker_json('inspect', prefix + service + '-1')[0]
        if container['Image'] != expected_id:
            raise ValueError('Running image differs from release plan: ' + service)
        if service == 'binaries-init':
            if container['State']['Status'] != 'exited' or container['State']['ExitCode'] != 0:
                raise ValueError('Binary initialization did not succeed')
        elif 'Health' in container['State']:
            if container['State']['Health']['Status'] != 'healthy':
                raise ValueError('Container is not healthy: ' + service)
        elif not container['State'].get('Running'):
            raise ValueError('Container is not running: ' + service)
    if not local_only:
        health = json.loads(fetch(settings['url'] + '/health'))
        if health.get('status') != 'ok' or health.get('version') != version:
            raise ValueError('API health/version mismatch')
    script = '''const fs=require('fs'),p=require('path');let found=false;
function visit(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){const f=p.join(d,e.name);if(e.isDirectory())visit(f);else if(f.endsWith('.js')){const s=fs.readFileSync(f,'utf8');if(s.includes('PUBLIC_APP_VERSION') && (s.includes('PUBLIC_APP_VERSION:`'+process.argv[1]+'`')||s.includes('PUBLIC_APP_VERSION:"'+process.argv[1]+'"')))found=true;}}}
const roots=[...new Set(['/app/dist/client','/app/apps/web/dist/client','/app/node_modules/.pnpm/node_modules/@breeze/web/dist/client'].filter(d=>fs.existsSync(d)).map(d=>fs.realpathSync(d)))];
if(roots.length!==1)process.exit(1);visit(roots[0]);if(!found)process.exit(1);'''
    run(['docker', 'exec', prefix + 'web-1', 'node', '-e', script, version], stdout=subprocess.DEVNULL)
    api_script = '''const fs=require('fs');if(process.env.APP_VERSION!==process.argv[1]||process.env.BINARY_VERSION!==process.argv[1]||process.env.PUBLIC_WEB_URL!==process.argv[2]||process.env.PUBLIC_APP_URL!==process.argv[2])process.exit(1);fs.accessSync('/data/binaries/VERSION');console.log(fs.readFileSync('/data/binaries/VERSION','utf8').trim());'''
    local_version = subprocess.check_output(['docker', 'exec', prefix + 'api-1', 'node', '-e', api_script, version, settings['url']], text=True).strip().lstrip('v')
    if local_version != version:
        raise ValueError('Local binary volume version mismatch')
    if local_only:
        return
    for path in ('/', '/quick', '/portal/'):
        fetch(settings['url'] + path)
    if settings.get('bookcentral_container'):
        run(['docker', 'exec', '-i', settings['bookcentral_container'], 'python'],
            input=(HERE / 'bookcentral-smoke.py').read_bytes(), stdout=subprocess.DEVNULL)


def needs_update(current, desired, app, version, images, settings, expected_ids):
    if current != desired:
        return True
    try:
        verify(app, version, images, settings, expected_ids, local_only=True)
        return False
    except (ValueError, OSError, subprocess.CalledProcessError, urllib.error.URLError):
        # Failed Compose jobs may have saved the target config before starting all services.
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('environment', choices=['dev', 'uat', 'production'])
    parser.add_argument('version')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    version_tuple(args.version)
    if os.geteuid() != 0:
        raise ValueError('Root required')
    os.umask(0o077)
    settings_all = json.loads((HERE.parent / 'config' / 'release-train.json').read_text())
    settings = settings_all['environments'][args.environment]
    lock_path = Path('/run/lock/breeze-signed-release-promotion.lock')
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        latest = release(SIGNED_REPO)['tag_name'].lstrip('v')
        if version_tuple(args.version) < version_tuple(latest):
            raise ValueError('Release superseded by latest signed release')
        from truenas_api_client import Client
        with Client() as client:
            app = settings['app']
            current = client.call('app.config', app)
            env = current['services']['api']['environment']
            check_no_downgrade(env, args.version)
            released = release(SIGNED_REPO, args.version)
            if released.get('draft') or released.get('prerelease'):
                raise ValueError('Draft/prerelease is not deployable')
            assets = {a['name']: a['browser_download_url'] for a in released['assets']}
            raw = fetch(assets['release-artifact-manifest.json'])
            signature = fetch(assets['release-artifact-manifest.json.ed25519'])
            verify_manifest(raw, signature, env['RELEASE_ARTIFACT_MANIFEST_PUBLIC_KEYS'])
            manifest = json.loads(raw)
            images = image_inventory(manifest, args.version)
            required_images = {'api', 'web', 'portal', 'binaries'} | set(current['services'])
            images = {name: image for name, image in images.items() if name in required_images}
            cache = HERE.parent / 'releases' / args.version
            cache.mkdir(parents=True, exist_ok=True)
            (cache / 'release-artifact-manifest.json').write_bytes(raw)
            (cache / 'release-artifact-manifest.json.ed25519').write_bytes(signature)
            # Verify actual signed installer bytes rather than only an environment string.
            verified_artifacts(manifest, assets, cache)
            images, overlays = prepare_images(images, manifest, args.version, settings)
            desired = desired_config(current, args.version, images, settings)
            services = {'api': 'api', 'web': 'web', 'portal': 'portal', 'binaries-init': 'binaries'}
            services.update({name: name for name in images if name not in {'api', 'web', 'portal', 'binaries'}})
            expected_ids = {s: docker_json('image', 'inspect', images[n])[0]['Id'] for s, n in services.items()}
            expected_plan = {'version': args.version, 'sourceCommit': manifest['sourceCommit'], 'images': images,
                             'expectedImageIds': expected_ids, 'overlays': overlays}
            (cache / (app + '-plan.json')).write_text(json.dumps(expected_plan, indent=2))
            if not args.verify_only and needs_update(current, desired, app, args.version, images, settings, expected_ids):
                backup(app, current, Path(settings_all['backup_root']))
                app_update(client, app, desired)
            deadline = time.monotonic() + 600
            last = None
            while time.monotonic() < deadline:
                try:
                    verify(app, args.version, images, settings, expected_ids)
                    print('promotion verified:', args.environment, 'web/api/portal/binaries/installer=' + args.version, flush=True)
                    return
                except (ValueError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as exc:
                    last = type(exc).__name__ + ': ' + str(exc)
                    time.sleep(10)
            raise RuntimeError('Release verification failed: ' + (last or 'unknown'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Full release promotion failed:', str(exc), file=sys.stderr)
        sys.exit(1)
