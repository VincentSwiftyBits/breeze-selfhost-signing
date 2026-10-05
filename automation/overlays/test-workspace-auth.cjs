const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {patch, bridgeSource} = require('./workspace-auth.cjs');

async function main() {
  const calls = [];
  const source = bridgeSource('/_astro/auth.test.js').replace(/^import[^\n]+\n/, '');
  const context = {URL, window: {location: {origin: 'https://prod.example.com'}}, swiftyWorkspaceApiFetch: (...args) => {calls.push(args); return {status: 200};}};
  vm.createContext(context);
  vm.runInContext(source, context);
  const signal = new AbortController().signal;
  await context.swiftyWorkspaceFetch('/api/v1/ext/workspace/sources?orgId=allowed-org', {method:'GET', signal});
  assert.equal(calls[0][0], '/ext/workspace/sources?orgId=allowed-org');
  assert.equal(calls[0][1].signal, signal);
  assert.equal(calls[0][1].skipOrgIdInjection, true);
  await context.swiftyWorkspaceFetch('/api/v1/ext/workspace/sources/s1?orgId=allowed-org', {method:'POST',body:'{"example":true}'});
  assert.equal(calls[1][1].body, '{"example":true}');
  assert.equal(calls[1][1].method, 'POST');
  for (const url of ['https://evil.example/api/v1/ext/workspace/sources', '//evil.example/api/v1/ext/workspace/sources', '/api/v1/users', '/api/v1/ext/workspace/../../users', 'https://user:pass@prod.example.com/api/v1/ext/workspace/sources', '/api/v1/ext/workspace/sources#fragment']) {
    await assert.rejects(context.swiftyWorkspaceFetch(url));
  }
  assert.equal(calls.length, 2, 'Invalid requests must never reach the authenticated host client');
  assert.throws(() => bridgeSource('https://evil.example/auth.js'));
  if (process.argv[2]) {
    const bundle = fs.readFileSync(process.argv[2], 'utf8');
    const result = patch(bundle, '/_astro/auth.test.js');
    assert.equal((result.match(/swiftyWorkspaceFetch\(/g) || []).length, 4);
    assert.throws(() => patch(result, '/_astro/auth.test.js'));
  }
  console.log('Workspace authenticated request bridge tests passed');
}
main().catch(error => {console.error(error); process.exit(1);});
