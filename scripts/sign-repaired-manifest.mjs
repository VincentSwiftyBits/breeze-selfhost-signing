import { createPrivateKey, createPublicKey, verify, sign } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const raw = (process.env.RELEASE_MANIFEST_ED25519_PRIVATE_KEY ?? '').trim();
if (!raw) throw new Error('Manifest signing key missing');
const key = raw.includes('BEGIN PRIVATE KEY') ? createPrivateKey(raw) :
  createPrivateKey({key: Buffer.from(raw, 'base64'), format: 'der', type: 'pkcs8'});
const pub = createPublicKey(key);
const current = readFileSync('existing/release-artifact-manifest.json');
const signature = Buffer.from(readFileSync('existing/release-artifact-manifest.json.ed25519', 'utf8').trim(), 'base64');
if (!verify(null, current, pub, signature)) throw new Error('Existing deployment signature verification failed');
const manifest = JSON.parse(current.toString('utf8'));
if (String(manifest.repository).toLowerCase() !== process.env.GITHUB_REPOSITORY.toLowerCase() ||
    manifest.release !== `v${process.env.VERSION}`) throw new Error('Existing release identity mismatch');
const result = spawnSync('python', ['scripts/repair_manifest_metadata.py',
  'existing/release-artifact-manifest.json', 'official/release-artifact-manifest.json',
  'existing', 'msi-evidence.json', 'repaired/release-artifact-manifest.json'], {encoding: 'utf8'});
if (result.status !== 0) throw new Error(`Repair validation failed: ${result.stderr}`);
const repaired = readFileSync('repaired/release-artifact-manifest.json');
const repairedSig = sign(null, repaired, key);
if (!verify(null, repaired, pub, repairedSig)) throw new Error('Repaired signature self-check failed');
writeFileSync('repaired/release-artifact-manifest.json.ed25519', repairedSig.toString('base64') + '\n');
console.log('Verified artifact bytes and identities; repaired and signed distribution metadata only.');
