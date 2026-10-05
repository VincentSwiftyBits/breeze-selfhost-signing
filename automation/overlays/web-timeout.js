// Preserve the established five-minute startup window for CPU-backed AI streams.
const fs = require('fs'), path = require('path');
const dirs=[...new Set(['/app/dist/client/_astro','/app/apps/web/dist/client/_astro','/app/node_modules/.pnpm/node_modules/@breeze/web/dist/client/_astro'].filter(p=>fs.existsSync(p)).map(p=>fs.realpathSync(p)))];
if (dirs.length !== 1) throw new Error(`Expected one web assets directory; found ${dirs.length}`);
const files=fs.readdirSync(dirs[0]).filter(n=>/^(aiStore|WorkspacePage)\..*\.js$/.test(n));
const pattern=/[A-Za-z_$][\w$]*\(`\/ai\/sessions\/\$\{[A-Za-z_$][\w$]*\}\/messages`,\{method:(?:`POST`|"POST"|'POST'),body:JSON\.stringify\(\{content:/g;
function appendSignal(s,marker) {
  const matches=[...s.matchAll(pattern)];
  if(matches.length!==1) throw new Error(`AI message call signature changed; matches=${matches.length}`);
  const start=s.indexOf('JSON.stringify(',matches[0].index)+'JSON.stringify'.length;
  let depth=0,quote=null,end=-1;
  for(let i=start;i<s.length;i++) {
    const c=s[i];
    if(quote) {if(c==='\\')i++;else if(c===quote)quote=null;continue;}
    if(c==='"'||c==="'"||c==='`'){quote=c;continue;}
    if(c==='(')depth++;else if(c===')'&&--depth===0){end=i+1;break;}
  }
  if(end<0||s.slice(end,end+2)!=='})'||!s.slice(start,end).includes('pageContext:')) throw new Error('Unexpected AI options/payload structure');
  return s.slice(0,end)+','+marker+s.slice(end);
}
let relevant=0;
for (const name of files) {
  const file=path.join(dirs[0],name); let s=fs.readFileSync(file,'utf8');
  if (!s.includes('/ai/sessions/') || !s.includes('/messages`')) continue;
  relevant++;
  const marker='signal:AbortSignal.timeout(3e5)';
  if (s.includes(marker)) continue;
  let matches=0;
  if (s.split('signal:AbortSignal.timeout(18e4)').length===2) {
    s=s.replace('signal:AbortSignal.timeout(18e4)',marker); matches=1;
  } else {s=appendSignal(s,marker);matches=1;}
  if(matches!==1) throw new Error(`AI request signature changed in ${name}; matches=${matches}`);
  const syntax=require('child_process').spawnSync(process.execPath,['--input-type=module','--check'],{input:s,encoding:'utf8'});
  if(syntax.status!==0) throw new Error(`Patched asset syntax invalid: ${name}: ${syntax.stderr}`);
  fs.writeFileSync(file,s);
}
if(!relevant) throw new Error('No AI message asset found');
