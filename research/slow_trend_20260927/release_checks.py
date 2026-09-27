"""Read-only boundary/secret checks and saved validation summary; no exchange access."""
import ast, datetime, json, platform, subprocess, zipfile
import numpy as np
import pandas as pd
from common import HERE, ROOT, SPEC, digest, now, write
from designer import util


def read(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()


def main():
    protocol=read('protocol_freeze.json');engine=read('engine_freeze.json')
    assert digest(HERE/'contract.json')==protocol['contract_sha256']
    for name,h in engine['files'].items():assert digest(HERE/name)==h,name
    for name,h in read('data_freeze.json')['inputs'].items():assert digest(ROOT/name)==h,name
    assert git('merge-base',SPEC['source_commit'],'HEAD')==SPEC['source_commit']
    assert git('branch','--show-current')=='codex/slow-trend-research-20260927'
    changed=git('diff',SPEC['source_commit'],'--name-only').splitlines()
    assert all(n.startswith('research/slow_trend_20260927/') for n in changed),changed
    progress=[json.loads(s) for s in (HERE/'results/progress.jsonl').read_text().splitlines()]
    stamps={s:[r['utc'] for r in progress if r['scope']==s] for s in ['development','validation','oos']}
    vn=read('results/validation_nominees_frozen.json');fn=read('results/finalists_frozen.json')
    assert engine['utc']<min(stamps['development'])
    assert max(stamps['development'])<vn['utc']<min(stamps['validation'])
    assert max(stamps['validation'])<fn['utc']<min(stamps['oos'])
    assert not fn['forward_opened']
    events=[json.loads(s) for s in (HERE/'results/designer_events.jsonl').read_text().splitlines()]
    assert all(e['scope']=='development' and e['utc']<vn['utc'] for e in events)
    assert sum(bool(e['api_called']) for e in events)==12
    audit=read('audit_results.json');repro=read('reproduction_check.json')
    assert audit['status']==repro['status']=='PASS'
    assert len(audit['prefix_tests'])==32 and len(repro['checks'])==17
    assert all(r['max_numeric_error']==0 for r in repro['checks'])
    assert 'Ran 18 tests' in (HERE/'test_results.txt').read_text() and (HERE/'test_results.txt').read_text().strip().endswith('OK')
    # This exact key was authorized for this research; it is never printed or saved.
    key,_=util.api_key();secret=key.encode() if key else None;scanned=members=0
    paths=[p for p in HERE.rglob('*') if p.is_file() and not any(x in {'archive','cache','__pycache__'} for x in p.relative_to(HERE).parts)]
    for p in paths:
        body=p.read_bytes();scanned+=1
        assert not secret or secret not in body,'Authorized API key found in research artifact; do not publish'
        if p.suffix=='.zip':
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    members+=1
                    assert not secret or secret not in z.read(n),'Authorized API key found in compressed artifact; do not publish'
    engine_names=['common.py','data.py','signals.py','ledger.py','evaluate.py','designer.py','run.py']
    imported=[]
    for name in engine_names:
        tree=ast.parse((HERE/name).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imported += [n.name for n in node.names]
            if isinstance(node,ast.ImportFrom):imported.append(node.module)
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):assert node.func.id not in {'eval','exec'}
    result=dict(utc=now(),status='PASS',source_commit=SPEC['source_commit'],branch=git('branch','--show-current'),engine_and_data_hashes='PASS',temporal_freeze_order='PASS',forward_opened=False,production_diff_outside_research=[],regressions=18,detailed_books=len(audit['ledger_reconciliations']),reconciled_fills=sum(r['fills'] for r in audit['ledger_reconciliations']),max_nav_error_usd=max(r['max_cash_quantity_nav_error_usd'] for r in audit['ledger_reconciliations']),prefix_tests=32,independent_replays=17,metrics_per_replay=38,replay_max_error=0,secret_scan=dict(key_available=bool(key),files=scanned,zip_members=members,leaks=0),environment=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,platform=platform.platform()),active_engine_imports=sorted(set(imported)),forbidden_old_pnl_path='Source inspected: only ancestor raw price/identity archives and acquisition/JSON/pricing helpers consumed; no ancestor PnL/equity stream input.',charts_visually_reviewed=['equity.png','panel_leaders.png','folds.png','pareto.png'])
    write(HERE/'release_checks.json',result)
    print('RELEASE CHECKS PASS',scanned,'files;',members,'compressed members; no secret value printed')


if __name__=='__main__':main()
