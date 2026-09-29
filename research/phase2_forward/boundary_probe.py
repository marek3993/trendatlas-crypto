"""Run inside a replica of the collector sandbox. Never read protected contents."""
import json
import os
from pathlib import Path

denied=['/opt/leadpilot','/var/lib/trendatlas-research','/opt/trendatlas-research',
        '/etc/credstore','/etc/credstore.encrypted','/root','/home','/run/credentials',
        '/run/docker.sock','/var/run/docker.sock','/opt/market_regime_v1','/opt/home_automation']
checks={p:{'readable':os.access(p,os.R_OK),'writable':os.access(p,os.W_OK)} for p in denied}
own=Path('/var/lib/trendatlas-phase2/status.json')
result={'uid':os.getuid(),'protected_paths':checks,'own_status_readable':os.access(own,os.R_OK),
        'credential_environment_present':bool(os.environ.get('CREDENTIALS_DIRECTORY'))}
print(json.dumps(result,sort_keys=True))
if os.getuid()==0 or not result['own_status_readable'] or any(v['readable'] or v['writable'] for v in checks.values()) or result['credential_environment_present']:
    raise SystemExit(1)
