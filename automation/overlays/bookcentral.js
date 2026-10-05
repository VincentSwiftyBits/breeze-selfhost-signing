// Preserve the scoped BookCentral ticket integration on each signed base image.
// Fail closed if upstream bundle structure changes; never silently omit the route.
const fs = require('fs');
const paths = ['/app/dist/index.cjs', '/app/apps/api/dist/index.cjs'].filter(p => fs.existsSync(p));
if (paths.length !== 1) throw new Error(`Expected exactly one API bundle; found ${paths.length}`);
const file = paths[0];
let src = fs.readFileSync(file, 'utf8');
function one(anchor, value) {
  const n = src.split(anchor).length - 1;
  if (n !== 1) throw new Error(`Expected one ${anchor}; found ${n}`);
  src = src.replace(anchor, value);
}
if (src.includes('api.route("/integrations/tickets", integrationTicketRoutes)')) {
  throw new Error('Upstream now contains ticket integration: review its authorization contract before dropping overlay');
}
for (const symbol of ['apiKeyAuthMiddleware','requireApiKeyScope','createTicketSchema','createTicket','TicketServiceError','deviceInSiteScope','zValidator']) {
  if (!new RegExp(`(?:function|var|const|let|class) ${symbol}(?:\\b|\\()|^\\s*${symbol} =`, 'm').test(src)) {
    throw new Error(`Required BookCentral dependency ${symbol} not present`);
  }
}
const scope = '"tickets:write": [PERMISSIONS.TICKETS_WRITE],';
if (!src.includes(scope)) {
  const anchor = '"alerts:write": [PERMISSIONS.ALERTS_WRITE],';
  one(anchor, `${anchor}\n      ${scope}`);
}
const anchor = 'api.route("/integrations", integrationRoutes);';
one(anchor, `// swiftybits scoped ticket integration overlay
api.post("/integrations/tickets", apiKeyAuthMiddleware, requireApiKeyScope("tickets:write"), zValidator("json", createTicketSchema), async (c) => {
  const apiKey = c.get("apiKey");
  const body = c.req.valid("json");
  if (!apiKey.orgId || body.orgId !== apiKey.orgId) return c.json({ error: "Access to this organization denied" }, 403);
  if (body.deviceId && !await deviceInSiteScope(apiKey, body.deviceId)) return c.json({ error: "Device not found or access denied" }, 403);
  try {
    const ticket = await createTicket({ ...body, source: "api" }, { userId: apiKey.createdBy, name: \`API key: \${apiKey.name}\` });
    return c.json({ data: ticket }, 201);
  } catch (err) {
    if (err instanceof TicketServiceError) return c.json(err.code ? { error: err.message, code: err.code } : { error: err.message }, err.status);
    throw err;
  }
});
${anchor}`);
fs.writeFileSync(file, src);
