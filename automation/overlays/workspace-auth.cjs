const fs = require('node:fs');

function bridgeSource(authModule) {
  if (!/^\/_astro\/auth\.[A-Za-z0-9_-]+\.js$/.test(authModule)) throw new Error('Unexpected host auth module');
  return `import {O as swiftyWorkspaceApiFetch} from ${JSON.stringify(authModule)};
async function swiftyWorkspaceFetch(input, init = {}) {
  if (typeof input !== 'string') throw new Error('Workspace request URL must be a string');
  const url = new URL(input, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/v1/ext/workspace/') || url.username || url.password || url.hash) {
    throw new Error('Workspace request must remain in its own same-origin API namespace');
  }
  return swiftyWorkspaceApiFetch(url.pathname.slice('/api/v1'.length) + url.search, {...init, skipOrgIdInjection: true});
}
`;
}

function patch(source, authModule) {
  if (source.includes('swiftyWorkspaceFetch')) throw new Error('Workspace auth bridge already installed');
  const needles = ['fetch(url2, {', 'fetch(config2.summaryUrl, {', 'fetch(config2.jobsUrl, {'];
  for (const needle of needles) {
    if (source.split(needle).length !== 2) throw new Error('Workspace fetch layout changed: ' + needle);
    source = source.replace(needle, needle.replace('fetch(', 'swiftyWorkspaceFetch('));
  }
  return bridgeSource(authModule) + source;
}

module.exports = {patch, bridgeSource};
if (require.main === module) {
  const [path, authModule] = process.argv.slice(2);
  if (!path || !authModule) throw new Error('Usage: workspace-auth.cjs bundle auth-module');
  fs.writeFileSync(path, patch(fs.readFileSync(path, 'utf8'), authModule));
}
