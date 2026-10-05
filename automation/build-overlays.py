#!/usr/bin/env python3
"""Build preserved integration images from the release's verified immutable bases.

stdin is the promoter release specification. stdout is JSON; build logs go stderr.
"""
import hashlib, json, pathlib, re, shutil, subprocess, sys, tarfile, tempfile, urllib.request

HERE=pathlib.Path(__file__).resolve().parent
OVERLAYS=HERE/'overlays'
def run(args, **kw):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=sys.stderr,check=True,**kw)
    return result.stdout.decode()
def build(args):
    subprocess.run(args,stdout=sys.stderr,stderr=sys.stderr,check=True)
def exists(tag,key,version,commit,base):
    result=subprocess.run(['docker','image','inspect',tag],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    if result.returncode: return False
    labels=json.loads(result.stdout)[0]['Config'].get('Labels') or {}
    expected={'io.swiftybits.breeze.overlay-sha':key,'org.opencontainers.image.version':version,'org.opencontainers.image.revision':commit,'io.swiftybits.breeze.base':base}
    if any(labels.get(k)!=v for k,v in expected.items()): raise RuntimeError('Existing overlay tag provenance does not match: '+tag)
    return True
def digest(parts):
    h=hashlib.sha256()
    for part in parts: h.update(part if isinstance(part,bytes) else str(part).encode())
    return h.hexdigest()[:20]
def main():
    spec=json.load(sys.stdin); version=spec['version']; commit=spec['sourceCommit']; bases=spec['images']
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version): raise ValueError('Invalid release version')
    if not re.fullmatch(r'[0-9a-f]{40}',commit): raise ValueError('Upstream sourceCommit must be full SHA')
    for base in bases.values():
        if not re.fullmatch(r'[a-z0-9./_-]+@sha256:[0-9a-f]{64}',base): raise ValueError('Immutable image digest required')
    result={'images':{},'provenance':{'sourceCommit':commit,'upstreamImages':bases,'overlays':{}}}
    with tempfile.TemporaryDirectory(prefix='breeze-overlays-') as tmp:
        tmp=pathlib.Path(tmp)
        msi=pathlib.Path(spec['signedMsiPath']); msi_sha=spec['signedMsiSha256']
        if not re.fullmatch('[a-f0-9]{64}',msi_sha) or hashlib.sha256(msi.read_bytes()).hexdigest()!=msi_sha:
            raise RuntimeError('Verified signed MSI required for binary initializer')
        base_config=json.loads(run(['docker','image','inspect',bases['binaries']]))[0]['Config']
        entrypoint=base_config.get('Entrypoint') or []
        if len(entrypoint)!=3 or entrypoint[:2]!=['sh','-c'] or '/binaries/* /target/' not in entrypoint[2]:
            raise RuntimeError('Binary initializer copy layout changed; review before deployment')
        key=digest([bases['binaries'],msi_sha]); tag=f'swiftybits/breeze-binaries:{version}-signed-msi-{key}'
        if not exists(tag,key,version,commit,bases['binaries']):
            ctx=tmp/'binaries'; ctx.mkdir(); shutil.copyfile(msi,ctx/'breeze-agent.msi')
            user=run(['docker','image','inspect',bases['binaries'],'--format','{{.Config.User}}']).strip() or 'root'
            if not re.fullmatch(r'[A-Za-z0-9_:-]+',user): raise RuntimeError('Base binaries image has unexpected runtime user')
            (ctx/'Dockerfile').write_text(f'FROM {bases["binaries"]}\nUSER root\nCOPY breeze-agent.msi /binaries/agent/breeze-agent.msi\nRUN chmod 0644 /binaries/agent/breeze-agent.msi\nUSER {user}\n')
            build(['docker','build','--label',f'io.swiftybits.breeze.overlay-sha={key}','--label',f'io.swiftybits.breeze.base={bases["binaries"]}','--label',f'org.opencontainers.image.version={version}','--label',f'org.opencontainers.image.revision={commit}','-t',tag,str(ctx)])
        result['images']['binaries']=tag; result['provenance']['overlays']['signedWindowsMsi']=msi_sha
        staged=run(['docker','run','--rm','--network','none','--read-only','--entrypoint','sh',tag,
                    '-c','sha256sum /binaries/agent/breeze-agent.msi']).split()[0]
        if staged!=msi_sha: raise RuntimeError('Binary initializer does not contain the verified signed MSI')
        api=tmp/'api'; api.mkdir()
        patch=(OVERLAYS/'bookcentral.js').read_bytes()
        tests=(OVERLAYS/'test-bookcentral.cjs').read_bytes()
        gateway_patch=(OVERLAYS/'openai-tool-search.cjs').read_bytes()
        gateway_tests=(OVERLAYS/'test-openai-tool-search.cjs').read_bytes()
        key=digest([bases['api'],patch,tests,gateway_patch,gateway_tests]); tag=f'swiftybits-breeze-api:{version}-integrations-{key}'
        if not exists(tag,key,version,commit,bases['api']):
            user=run(['docker','image','inspect',bases['api'],'--format','{{.Config.User}}']).strip() or 'root'
            if not re.fullmatch(r'[A-Za-z0-9_:-]+',user): raise RuntimeError('Base API image has unexpected runtime user')
            (api/'bookcentral.js').write_bytes(patch)
            (api/'test-bookcentral.cjs').write_bytes(tests)
            (api/'openai-tool-search.cjs').write_bytes(gateway_patch)
            (api/'test-openai-tool-search.cjs').write_bytes(gateway_tests)
            (api/'Dockerfile').write_text(f'FROM {bases["api"]}\nUSER root\nCOPY bookcentral.js test-bookcentral.cjs openai-tool-search.cjs test-openai-tool-search.cjs /tmp/\nRUN bundle=$(find /app/dist /app/apps/api/dist -name index.cjs 2>/dev/null); node /tmp/test-bookcentral.cjs "$bundle" && node /tmp/bookcentral.js && node /tmp/test-openai-tool-search.cjs "$bundle" --baseline && node /tmp/openai-tool-search.cjs "$bundle" && node /tmp/test-openai-tool-search.cjs "$bundle" && node --check "$bundle" && rm /tmp/bookcentral.js /tmp/test-bookcentral.cjs /tmp/openai-tool-search.cjs /tmp/test-openai-tool-search.cjs\nUSER {user}\n')
            build(['docker','build','--label',f'io.swiftybits.breeze.overlay-sha={key}','--label',f'io.swiftybits.breeze.base={bases["api"]}','--label',f'org.opencontainers.image.version={version}','--label',f'org.opencontainers.image.revision={commit}','-t',tag,str(api)])
        result['images']['api']=tag; result['provenance']['overlays']['bookcentral']=key
        if spec.get('vendorhub'):
            files=[p for p in sorted(OVERLAYS.rglob('*')) if p.is_file() and (p.name=='vendorhub.py' or 'vendorhub' in p.parts)]
            key=digest([bases['web'],commit]+[p.read_bytes() for p in files]); tag=f'swiftybits/breeze-web:{version}-vendorhub-{key}'
            if not exists(tag,key,version,commit,bases['web']):
                archive=tmp/'source.tar.gz'
                urllib.request.urlretrieve(f'https://codeload.github.com/LanternOps/breeze/tar.gz/{commit}',archive)
                source=tmp/'source'; source.mkdir()
                with tarfile.open(archive) as tar: tar.extractall(source,filter='data')
                roots=list(source.iterdir())
                if len(roots)!=1 or not roots[0].is_dir(): raise RuntimeError('Unexpected source archive structure')
                root=roots[0]
                run([sys.executable,str(OVERLAYS/'vendorhub.py'),str(root)])
                build(['docker','build','--build-arg',f'PUBLIC_APP_VERSION={version}','--build-arg','PUBLIC_API_URL=','--label',f'io.swiftybits.breeze.overlay-sha={key}','--label',f'io.swiftybits.breeze.base={bases["web"]}','--label',f'org.opencontainers.image.version={version}','--label',f'org.opencontainers.image.revision={commit}','-f',str(root/'docker/Dockerfile.web'),'-t',tag,str(root)])
            result['images']['web']=tag; result['provenance']['overlays']['vendorhub']=key
        webbase=result['images'].get('web',bases['web']); timeout=(OVERLAYS/'web-timeout.js').read_bytes()
        key=digest([webbase,timeout]); tag=f'swiftybits/breeze-web:{version}-ai-timeout-{key}'
        if not exists(tag,key,version,commit,webbase):
            ctx=tmp/'web-timeout'; ctx.mkdir(); (ctx/'web-timeout.js').write_bytes(timeout)
            user=run(['docker','image','inspect',webbase,'--format','{{.Config.User}}']).strip() or 'root'
            if not re.fullmatch(r'[A-Za-z0-9_:-]+',user): raise RuntimeError('Base web image has unexpected runtime user')
            (ctx/'Dockerfile').write_text(f'FROM {webbase}\nUSER root\nCOPY web-timeout.js /tmp/web-timeout.js\nRUN node /tmp/web-timeout.js && rm /tmp/web-timeout.js\nUSER {user}\n')
            build(['docker','build','--label',f'io.swiftybits.breeze.overlay-sha={key}','--label',f'io.swiftybits.breeze.base={webbase}','--label',f'org.opencontainers.image.version={version}','--label',f'org.opencontainers.image.revision={commit}','-t',tag,str(ctx)])
        result['images']['web']=tag; result['provenance']['overlays']['ai-timeout']=key
    print(json.dumps(result))
if __name__=='__main__': main()
