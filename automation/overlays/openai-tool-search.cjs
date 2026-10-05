const fs = require('node:fs');

function patch(source) {
  const changes = [
    ['imageBlock, toolUseBlock, toolResultBlock, droppedBlock',
     'imageBlock, toolUseBlock, toolReferenceBlock, toolResultBlock, droppedBlock'],
    ['    toolResultBlock = import_zod102.z.object({',
     '    toolReferenceBlock = import_zod102.z.object({ type: import_zod102.z.literal("tool_reference"), tool_name: import_zod102.z.string().min(1) }).passthrough();\n    toolResultBlock = import_zod102.z.object({'],
    ['import_zod102.z.array(import_zod102.z.union([textBlock, imageBlock]))]).optional()',
     'import_zod102.z.array(import_zod102.z.union([textBlock, imageBlock, toolReferenceBlock]))]).optional()'],
    ['b.type === "text" ? b.text : "[image omitted]"',
     'b.type === "text" ? b.text : b.type === "tool_reference" ? `Available tool: ${b.tool_name}` : "[image omitted]"'],
  ];
  for (const [before, after] of changes) {
    if (source.split(before).length !== 2) throw new Error('OpenAI tool-search gateway layout changed; review before deployment');
    source = source.replace(before, after);
  }
  return source;
}

if (require.main === module) {
  const bundle = process.argv[2];
  if (!bundle) throw new Error('Explicit API bundle path required');
  fs.writeFileSync(bundle, patch(fs.readFileSync(bundle, 'utf8')));
}
module.exports = { patch };
