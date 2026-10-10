"""Host-pressure admission and cooperative checkpoints for research only."""
import json
import math
import os
from pathlib import Path
import shutil
import time

from research.continuous_research.common import atomic, utc


class ResourcePause(RuntimeError):
    pass


def limits():
    return json.loads((Path(__file__).resolve().parents[1]/'source_of_truth/research_meta_policy_v1.json').read_text())['resources']


def observe(root):
    def ticks():
        values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        return sum(values), values[3]+values[4]
    before, idle_before = ticks(); time.sleep(.2); total, idle = ticks()
    if total <= before:
        raise ValueError('cpu_sample_unavailable')
    memory = {line.split(':')[0]: int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
    def pressure(kind, row):
        line = next(x for x in (Path('/proc/pressure')/kind).read_text().splitlines() if x.startswith(row+' '))
        return float(dict(item.split('=') for item in line.split()[1:])['avg10'])
    path = Path(root)/'research.sqlite'
    return {'utc': utc(), 'cpu_busy_pct': 100*(1-(idle-idle_before)/(total-before)),
            'load_per_cpu': os.getloadavg()[0]/max(1, os.cpu_count() or 1),
            'cpu_pressure': pressure('cpu', 'some'), 'memory_available': memory['MemAvailable'],
            'memory_pressure': pressure('memory', 'full'), 'io_pressure': pressure('io', 'full'),
            'disk_free': shutil.disk_usage(root).free,
            'ledger_bytes': sum(p.stat().st_size for p in (path, Path(str(path)+'-wal')) if p.exists())}


def decision(value):
    c = limits()
    fields = ('cpu_busy_pct', 'load_per_cpu', 'cpu_pressure', 'memory_available', 'memory_pressure',
              'io_pressure', 'disk_free', 'ledger_bytes')
    if any(type(value[k]) not in (int, float) or not math.isfinite(value[k]) or value[k] < 0 for k in fields):
        raise ValueError('invalid_resource_observation')
    for field, bound, reason in (
        ('cpu_busy_pct', c['cpu_busy_max_pct'], 'CPU'), ('load_per_cpu', c['load_per_cpu_max'], 'CPU'),
        ('cpu_pressure', c['cpu_pressure_some_avg10_max'], 'CPU_PRESSURE'),
        ('memory_pressure', c['memory_pressure_full_avg10_max'], 'MEMORY_PRESSURE'),
        ('io_pressure', c['io_pressure_full_avg10_max'], 'IO_PRESSURE'),
        ('ledger_bytes', c['ledger_max_bytes'], 'LEDGER_CAPACITY')):
        if value[field] >= bound:
            return 'WAIT_RESOURCE_'+reason
    if value['memory_available'] < c['memory_available_min_bytes']:
        return 'WAIT_RESOURCE_MEMORY'
    if value['disk_free'] < c['disk_reserve_bytes']+c['incoming_book_reserve_bytes']:
        return 'WAIT_RESOURCE_DISK'
    return None


def admit(root, observer=observe):
    try:
        value = observer(root); reason = decision(value)
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        value = {'utc': utc(), 'error_type': type(exc).__name__}; reason = 'WAIT_RESOURCE_OBSERVATION'
    atomic(Path(root)/'resources.json', {'sample': value, 'state': reason or 'ADMITTED'})
    if reason:
        raise ResourcePause(reason)
    return value
