// Exercise the actual injected handler extracted from a real upstream bundle.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let source=fs.readFileSync(process.argv[2],'utf8');
const fakefs={existsSync:p=>p==='/app/apps/api/dist/index.cjs',readFileSync:()=>source,writeFileSync:(_,s)=>source=s};
vm.runInNewContext(fs.readFileSync(__dirname+'/bookcentral.js','utf8'),{require:()=>fakefs});
const start=source.indexOf('// swiftybits scoped ticket integration overlay');
const end=source.indexOf('api.route("/integrations", integrationRoutes);',start);
let handler, middleware, created=[],scopeAllowed=true;
class TicketServiceError extends Error { constructor(message,status,code){super(message);this.status=status;this.code=code;} }
const keyAuth={},scopeMiddleware={},validator={};
const sandbox={api:{post:(path,...args)=>{assert.equal(path,'/integrations/tickets');handler=args.pop();middleware=args;}},apiKeyAuthMiddleware:keyAuth,requireApiKeyScope:scope=>{assert.equal(scope,'tickets:write');return scopeMiddleware;},zValidator:(kind,schema)=>{assert.equal(kind,'json');return validator;},createTicketSchema:{},deviceInSiteScope:async(key,id)=>scopeAllowed,createTicket:async(input,actor)=>{created.push({input,actor});return {id:'ticket-id'};},TicketServiceError};
vm.runInNewContext(source.slice(start,end),sandbox);
assert.deepEqual(middleware,[keyAuth,scopeMiddleware,validator]);
function ctx(key,body){return {get:()=>key,req:{valid:()=>body},json:(data,status)=>({data,status})};}
(async()=>{
 const key={orgId:'org-a',createdBy:'owner',name:'BookCentral'};
 for(const key2 of [{...key,orgId:null},key]){
  const r=await handler(ctx(key2,{orgId:'org-b',subject:'Test'}));assert.equal(r.status,403);assert.equal(created.length,0);
 }
 scopeAllowed=false;
 assert.equal((await handler(ctx(key,{orgId:'org-a',deviceId:'denied',subject:'Test'}))).status,403);assert.equal(created.length,0);
 scopeAllowed=true;
 const r=await handler(ctx(key,{orgId:'org-a',deviceId:'allowed',subject:'Test'}));assert.equal(r.status,201);assert.equal(created[0].input.source,'api');assert.equal(created[0].actor.userId,'owner');
 sandbox.createTicket=async()=>{throw new TicketServiceError('Denied',400,'WRONG_ORG')};
 const error=await handler(ctx(key,{orgId:'org-a',subject:'Test'}));assert.equal(error.status,400);assert.equal(error.data.code,'WRONG_ORG');
 console.log('BookCentral real-bundle middleware, org/site denial, success, and service-error tests passed');
})().catch(e=>{console.error(e);process.exitCode=1});
