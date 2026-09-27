"""Cooperative resource/production guard, in addition to systemd hard limits."""
import os
import shutil
import signal
import time
from pathlib import Path
from .protocol import CONTRACT, utc

class PauseResearch(Exception):pass

class Guard:
    def __init__(self,store,pi=False,seconds=None):
        self.store=store;self.pi=pi;self.start=time.monotonic();self.last=0.;self.stop=False
        self.seconds=seconds or CONTRACT['runtime']['per_activation_minutes']*60
        self.prior=float(store.meta('active_seconds',0));self.cpu=time.process_time()
        if pi:
            signal.signal(signal.SIGTERM,self.request_stop);signal.signal(signal.SIGINT,self.request_stop)

    def request_stop(self,*_):self.stop=True

    def __call__(self,force=False):
        now=time.monotonic()
        if not force and now-self.last<3:return
        self.last=now;elapsed=now-self.start
        reason=None
        if self.stop:reason='production_preemption_or_service_stop'
        if elapsed>=self.seconds:reason='bounded_activation_checkpoint'
        if self.prior+elapsed>=CONTRACT['budget']['active_seconds_ceiling']:raise RuntimeError('Whole-cycle active time budget exhausted')
        sizes=sum(p.stat().st_size for p in self.store.root.rglob('*') if p.is_file())
        if sizes>CONTRACT['budget']['state_bytes_ceiling']:raise RuntimeError('Frozen result storage budget exhausted')
        resource=dict(utc=utc(),elapsed_seconds=elapsed,process_cpu_seconds=time.process_time()-self.cpu,state_bytes=sizes,
                      disk_free_mib=shutil.disk_usage(self.store.root).free/1024**2,pi=self.pi)
        if self.pi:
            from .gate import allowed,properties,parse_jobs
            import subprocess
            jobs=subprocess.run(['/usr/bin/systemctl','list-jobs','--no-legend','--no-pager'],capture_output=True,text=True,check=True,timeout=5)
            if not allowed(properties('mrv1-production.service'),properties('mrv1-production.timer'),parse_jobs(jobs.stdout)):reason='production_has_priority'
            status={line.split(':')[0]:line.split(':')[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if ':' in line}
            resource.update(rss_kib=int(status['VmRSS'].split()[0]),swap_kib=int(status['VmSwap'].split()[0]),locked_kib=int(status['VmLck'].split()[0]))
            temperatures=[int(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
            resource['temperature_c']=max(temperatures) if temperatures else None
            if not temperatures:reason='thermal_sensor_unavailable'
            elif max(temperatures)>=CONTRACT['runtime']['thermal_stop_c']:reason='thermal_guard'
            if resource['swap_kib']!=0:raise RuntimeError('No-swap invariant failed')
            if resource['disk_free_mib']<CONTRACT['runtime']['disk_free_reserve_mib']:reason='disk_reserve'
        self.store.set('resources',resource);self.store.set('active_seconds',self.prior+elapsed)
        self.store.set('pause_reason',reason);self.store.status()
        if reason:raise PauseResearch(reason)

def lock_memory():
    """Pi lacks memory cgroup controller: RLIMIT_AS + mlockall enforce the fallback."""
    import ctypes
    import resource
    ceiling=CONTRACT['runtime']['ram_max_mib']*1024**2
    resource.setrlimit(resource.RLIMIT_AS,(ceiling,ceiling))
    resource.setrlimit(resource.RLIMIT_MEMLOCK,(ceiling,ceiling))
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.mlockall(1|2)!=0:raise RuntimeError('mlockall failed errno='+str(ctypes.get_errno()))
    return dict(virtual_memory_cap_bytes=ceiling,mlockall_current_future=True,
                mechanism='RLIMIT_AS+RLIMIT_MEMLOCK+mlockall; memory cgroup absent')
