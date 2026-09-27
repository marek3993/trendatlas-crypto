import json,subprocess
from pathlib import Path
name='trendatlas-causal-boundary-probe.service'
base=Path('/etc/systemd/system/trendatlas-causal-broker.service').read_text()
checks={
 'production_head':'/opt/market_regime_v1/.git/HEAD',
 'candidates':'/var/lib/trendatlas-research/causal-v1/current/candidates.sqlite',
 'raw_data':'/opt/trendatlas-research/releases/53b6a5336ca1f7ce35b481a017f7e82396f3613c/research/causal_evolution/inputs/spot_daily.zip',
 'development_mailbox':'/var/lib/trendatlas-causal-broker/mailbox/proposals.sqlite'}
code="import os,json; p="+repr(checks)+"; r={k:os.access(v,os.R_OK) for k,v in p.items()}; print(json.dumps(r)); assert r==dict(production_head=False,candidates=False,raw_data=False,development_mailbox=True)"
body='\n'.join(line for line in base.splitlines() if not line.startswith(('ExecStart=','ExecCondition=','LoadCredentialEncrypted=','RuntimeMaxSec=')))
body+='\nTimeoutStartSec=30s\nExecStart=/usr/bin/python3 -c '+json.dumps(code)+'\n'
p=Path('/run/systemd/system')/name
try:
 p.write_text(body)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 r=subprocess.run(['systemctl','start',name],capture_output=True,text=True)
 j=subprocess.run(['journalctl','-u',name,'-n','8','--no-pager','-o','cat'],capture_output=True,text=True)
 print(json.dumps(dict(exit_code=r.returncode,journal=j.stdout,stderr=r.stderr)))
 assert r.returncode==0
finally:
 subprocess.run(['systemctl','stop',name],capture_output=True)
 p.unlink(missing_ok=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
