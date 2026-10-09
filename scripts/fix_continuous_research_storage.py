"""Apply the compatible shared-WAL permission contract without changing SQL data."""
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path


def main():
    if os.geteuid()!=0:raise ValueError('research_admin_required')
    root=Path('/var/lib/trendatlas-continuous-mailbox');db=root/'api.sqlite'
    gid=root.stat().st_gid;before=[];after=[]
    for path in (db,root/'api.sqlite-wal',root/'api.sqlite-shm'):
        try:s=path.lstat()
        except FileNotFoundError:continue
        if not stat.S_ISREG(s.st_mode) or s.st_gid!=gid:raise ValueError('unexpected_shared_file')
        before.append({'path':str(path),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode))})
        try:
            path.chmod(0o660);s=path.stat()
            after.append({'path':str(path),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode))})
        except FileNotFoundError:
            if path==db:raise
            # A writer may finish/checkpoint and remove an ephemeral sidecar.
            after.append({'path':str(path),'state':'sidecar_closed_concurrently'})
    drop=Path('/etc/systemd/system/trendatlas-continuous-broker.service.d/shared-wal.conf')
    body='[Service]\nExecStartPre=/usr/bin/chmod 0660 /var/lib/trendatlas-continuous-mailbox/api.sqlite\n'
    if drop.exists() and drop.read_text()!=body:raise ValueError('unexpected_existing_dropin')
    drop.parent.mkdir(exist_ok=True);drop.write_text(body)
    subprocess.run(['systemd-analyze','verify','/etc/systemd/system/trendatlas-continuous-broker.service'],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print(json.dumps({'before':before,'after':after,'dropin':str(drop),'dropin_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'SQL_records_changed':False,'legacy_paths_changed':False,'restart_requested':False}))


if __name__=='__main__':main()
