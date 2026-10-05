const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {createRequire} = require('node:module');

const bundle = process.argv[2];
const source = fs.readFileSync(bundle, 'utf8');
const start = source.indexOf('// src/services/aiModels/gateway/openai/translateRequest.ts');
const end = source.indexOf('// src/services/aiModels/gateway/openai/adapter.ts', start);
assert(start >= 0 && end > start, 'Gateway source layout must be recognized');
class GatewayError extends Error { constructor(status, type, code, message) { super(message); this.status=status; } }
const context = vm.createContext({require:createRequire(bundle), GatewayError, GATEWAY_MAX_TOOLS:512,
  init_limits(){},init_types4(){},__esm:definitions=>()=>Object.values(definitions)[0]()});
vm.runInContext(source.slice(start,end)+'\ninit_translateRequest();',context);

const request = {model:'gpt-4.1-nano',max_tokens:256,
  tools:[{name:'ToolSearch',input_schema:{type:'object',properties:{query:{type:'string'}}}},
         {name:'mcp__breeze__get_device',description:'Look up a device',input_schema:{type:'object',properties:{id:{type:'string'}}}}],
  messages:[{role:'user',content:'Find the device lookup tool. Do not access device data.'},
    {role:'assistant',content:[{type:'tool_use',id:'call_search',name:'ToolSearch',input:{query:'device lookup'}}]},
    {role:'user',content:[{type:'tool_result',tool_use_id:'call_search',content:[{type:'tool_reference',tool_name:'mcp__breeze__get_device'}]}]}]};
if (process.argv.includes('--baseline')) {
  assert.throws(()=>context.translateMessagesRequest(request,'gpt-4.1-nano'), /Content block type "tool_result"/);
  console.log('Confirmed upstream tool-search round-trip incompatibility');
  process.exit(0);
}
const result = context.translateMessagesRequest(request,'gpt-4.1-nano');
const message = result.body.messages.find(m=>m.role==='tool');
assert.equal(message.tool_call_id,'call_search');
assert.equal(message.content,'Available tool: mcp__breeze__get_device');
assert.equal(result.body.tools.length,2);
assert.equal(result.tools.fromOai.get(result.body.tools[1].function.name),'mcp__breeze__get_device');
request.messages[2].content[0].content=[{type:'text',text:'Legacy tool result'}];
assert.equal(context.translateMessagesRequest(request,'gpt-4.1-nano').body.messages[2].content,'Legacy tool result');
request.messages[2].content[0].content=[{type:'tool_reference',tool_name:''}];
assert.throws(()=>context.translateMessagesRequest(request,'gpt-4.1-nano'),/Content block type "tool_result"/);
request.messages[2].content[0].content=[{type:'unsupported_privileged_block',data:'reject'}];
assert.throws(()=>context.translateMessagesRequest(request,'gpt-4.1-nano'),/Content block type "tool_result"/);
console.log('OpenAI tool-search round trip and strict validation passed');
