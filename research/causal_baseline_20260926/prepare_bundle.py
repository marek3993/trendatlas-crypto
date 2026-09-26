"""Merge verified read-only captures into one public, privacy-minimized archive."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import zipfile
from collect_inputs import sha, safe_path, public_payload

def merge(sources, output):
    if output.exists():
        raise FileExistsError(output)
    entries, captures = {}, []
    for path in sources:
        manifest = json.loads(path.with_suffix('.manifest.json').read_text())
        if sha(path.read_bytes()) != manifest['bundle_sha256']:
            raise ValueError('Capture archive changed')
        captures.append({k:manifest[k] for k in ('capture_utc','bundle_sha256','unavailable')})
        with zipfile.ZipFile(path) as z:
            if set(z.namelist()) != set(manifest['files']):
                raise ValueError('Capture member mismatch')
            for name, meta in manifest['files'].items():
                safe_path(name)
                content = z.read(name)
                if sha(content) != meta['sha256']:
                    raise ValueError('Capture member changed: '+name)
                if name.endswith(('execution_plan.json', 'live_preflight.json')):
                    continue
                clean = public_payload(name, content)
                stored = dict(meta, sha256=sha(clean), size=len(clean),
                              redacted=meta['redacted'] or clean != content)
                if name in entries and entries[name][2]['original_sha256'] != stored['original_sha256']:
                    raise ValueError('Source changed between captures: '+name)
                entries[name] = (z.getinfo(name), clean, stored)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, (info, content, _) in sorted(entries.items()):
            z.writestr(info, content)
    manifest = {'schema_version':1, 'source':'Pi read-only SFTP /opt/market_regime_v1',
                'capture_utc':max(c['capture_utc'] for c in captures), 'captures':captures,
                'files':{n: e[2] for n,e in sorted(entries.items())}, 'unavailable':{},
                'bundle_sha256':sha(output.read_bytes()),
                'remote_operations':['listdir','lstat','stat','open_rb'], 'remote_writes':False,
                'account_address_saved':False,
                'privacy':'Run manifests retain model target and stage times only; account and order payloads excluded.'}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'files':len(entries),'bundle_sha256':manifest['bundle_sha256']}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,action='append',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();merge(a.source,a.output)
