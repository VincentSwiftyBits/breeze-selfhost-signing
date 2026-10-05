"""Apply the independent Vendor Hub UI to a verified upstream source checkout."""
import json, pathlib, re, shutil, sys
root=pathlib.Path(sys.argv[1]); overlay=pathlib.Path(__file__).parent/'vendorhub'
sidebar=root/'apps/web/src/components/layout/Sidebar.tsx'
text=sidebar.read_text(encoding='utf-8')
if '/vendors-suppliers' in text: raise RuntimeError('Vendor navigation is already present; review upstream contract')
anchor="  Power,"
if text.count(anchor)!=1: raise RuntimeError('Sidebar icon import changed')
text=text.replace(anchor,anchor+'\n  Handshake,')
pattern=r"^(  \{ name: 'Organizations'.*partnerScopeOnly: true.*requiredPermission:.*\},)$"
matches=list(re.finditer(pattern,text,re.M))
if len(matches)!=1: raise RuntimeError('Partner Organizations navigation anchor changed')
nav="  { name: 'Vendors & Suppliers', labelKey: 'nav.vendorsAndSuppliers', href: '/vendors-suppliers', icon: Handshake, partnerScopeOnly: true, requiredPermission: { resource: 'organizations', action: 'read' } },"
text=text[:matches[0].end()]+'\n'+nav+text[matches[0].end():]
sidebar.write_text(text,encoding='utf-8')
for locale in ['en','pt-BR']:
    path=root/f'apps/web/src/locales/{locale}/common.json'
    obj=json.loads(path.read_text(encoding='utf-8')); obj['nav']['vendorsAndSuppliers']='Vendors & Suppliers'
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for source in overlay.rglob('*'):
    if source.is_file():
        dest=root/'apps/web/src'/source.relative_to(overlay)
        dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,dest)
