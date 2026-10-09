import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def instant(value=None):return datetime.fromisoformat(value or utc()).astimezone(timezone.utc)
def period(value=None):
    t=instant(value).astimezone(ZoneInfo('Europe/Paris'))
    return t.date().isoformat(),t.strftime('%Y-%m')


def atomic_bytes(path,body):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.tmp')
    with temp.open('wb') as out:out.write(body);out.flush();os.fsync(out.fileno())
    os.replace(temp,path)
    if os.name!='nt':
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)


def atomic(path,body):atomic_bytes(path,(canonical(body)+'\n').encode())


def process_token(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().split(') ')[1].split()[19]
    except (OSError,IndexError):return None


def lease(root,phase,**fields):
    active=phase not in ('IDLE','WAIT','DONE')
    atomic(Path(root)/'lease.json',{'phase':phase,'pid':os.getpid() if active else 0,
        'process_token':process_token(os.getpid()) if active else None,'utc':utc(),
        'expires':(instant()+timedelta(seconds=300)).isoformat(),**fields})


def live_lease(root):
    try:
        value=json.loads((Path(root)/'lease.json').read_text());pid=value['pid']
        if not pid or instant(value['expires'])<instant():return None
        try:os.kill(pid,0)
        except PermissionError:return {**value,'pid_verified':False}
        if value['process_token'] is not None and process_token(pid)!=value['process_token']:return None
        return {**value,'pid_verified':True}
    except (OSError,ValueError,KeyError):return None
