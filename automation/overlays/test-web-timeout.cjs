const fs=require('fs'),vm=require('vm'),assert=require('assert');
const patch=fs.readFileSync(__dirname+'/web-timeout.js','utf8');
function apply(source){
 let result=source;
 const fakefs={existsSync:p=>p==='/app/dist/client/_astro',realpathSync:p=>p,readdirSync:()=>['aiStore.example.js'],readFileSync:()=>source,writeFileSync:(_,s)=>result=s};
 vm.runInNewContext(patch,{require:n=>n==='fs'?fakefs:require(n),process});return result;
}
const old='f(`/ai/sessions/${s}/messages`,{method:`POST`,body:JSON.stringify({content:c,pageContext:p??void 0})})';
const latest='f(`/ai/sessions/${s}/messages`,{method:`POST`,body:JSON.stringify({content:c,pageContext:p??void 0,...(m&&!n?{model:m}:{})})})';
for(const input of [old,latest]){
 const output=apply(input);assert(output.includes(',signal:AbortSignal.timeout(3e5)}'));assert.equal(apply(output),output);new vm.Script(output);
}
assert.throws(()=>apply(latest+latest));assert.throws(()=>apply('f("/other",{})'));
if(process.argv[2]){
 const result=apply(fs.readFileSync(process.argv[2],'utf8'));
 const check=require('child_process').spawnSync(process.execPath,['--input-type=module','--check'],{input:result,encoding:'utf8'});assert.equal(check.status,0,check.stderr);
 console.log('Actual compiled web asset patched and syntax verified');
}
console.log('AI timeout original/new payload, idempotence, ambiguity rejection tests passed');
