"""Freeze only authorized historical prices and model targets, never PnL."""
import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from .contract import load, allowed

def guarded_rows(stream, contract, end=None):
    """Read timestamp before interpreting any remaining columns of a row."""
    header = stream.readline().decode('utf-8-sig').strip()
    keys = next(csv.reader([header]))
    previous = None
    cutoff = end or contract['authorized_development'][-1][1]
    while True:
        prefix = bytearray()
        while True:
            char = stream.read(1)
            if char in (b'', b',', b'\n'):
                break
            prefix.extend(char)
        if not prefix:
            break
        text = prefix.decode().strip('"\r ')
        day = text[:10]
        if day > cutoff:
            break  # Do not parse future price, target, exposure or return columns.
        rest = stream.readline()
        if not allowed(day, contract):
            continue
        if previous and day <= previous:
            raise ValueError('duplicate_or_unsorted_input_date')
        previous = day
        values = next(csv.reader([prefix.decode() + ',' + rest.decode().strip()]))
        if len(values) != len(keys):
            raise ValueError('input_csv_shape')
        yield dict(zip(keys, values))

def freeze_local(root, destination):
    c = load()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    prices = {}
    evidence = []
    for directory in ('data/ohlcv_phase67_top100', 'data/ohlcv'):
        for path in sorted((Path(root)/directory).glob('*_1d.csv')):
            symbol = path.name.removesuffix('_1d.csv')
            rows = []
            with path.open('rb') as stream:
                for row in guarded_rows(stream, c):
                    values = [row['date'][:10]] + [row[k] for k in ('open','high','low','close')]
                    # Explicit volume proxy; not misrepresented as exchange quote volume.
                    quote = float(row['volume']) * float(row['close'])
                    rows.append(values + [format(quote,'.17g')])
            if rows:
                prices[symbol] = rows
                evidence.append({'source':directory+'/'+path.name,'first':rows[0][0], 'last':rows[-1][0],
                    'rows':len(rows), 'slice_hash':hashlib.sha256(json.dumps(rows).encode()).hexdigest()})
    with zipfile.ZipFile(destination/'local_spot_daily.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for symbol, rows in sorted(prices.items()):
            buf = io.StringIO(); writer = csv.writer(buf)
            writer.writerow(['date','open','high','low','close','quote_volume']); writer.writerows(rows)
            archive.writestr(symbol+'.csv',buf.getvalue())
    underlying={}
    baseline=Path(root)/'outputs/execution/app_exports/phase67j_no_neo_main_paper.csv'
    with baseline.open('rb') as stream:
        for row in guarded_rows(stream,c):underlying[row['date'][:10]]=row
    targets = []
    with (Path(root)/'outputs/production/current_strategy_timeseries.csv').open('rb') as stream:
        for row in guarded_rows(stream,c):
            if row['strategy_version'] != 'phase68g_etf_flow_impulse_early_risk_cooldown_15':
                raise ValueError('production_reference_version')
            target={k:row[k] for k in ('date','strategy_version','execution_target_asset','execution_target_exposure')}
            target['original_target_asset']=target['execution_target_asset'];target['asset_resolution']='canonical_target'
            target['original_target_exposure']=target['execution_target_exposure']
            if target['execution_target_asset']=='BASE':
                base_row=underlying.get(target['date'][:10],{})
                symbol=base_row.get('executed_position','').strip().upper()
                if base_row.get('executed_regime')!='BASE' or base_row.get('chosen_asset'):
                    raise ValueError('BASE_source_is_another_overlay:'+target['date'])
                if symbol=='CASH':
                    target['execution_target_exposure']='0.0'
                elif not symbol.endswith('USDT') or symbol in ('BASEUSDT','ALTUSDT'):
                    raise ValueError('unresolved_BASE_target:'+target['date'])
                target['execution_target_asset']=symbol.removesuffix('USDT')
                target['asset_resolution']='phase67j_no_neo_main_paper::executed_position_same_date'
            targets.append(target)
    with (destination/'production_targets.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(targets[0])); writer.writeheader(); writer.writerows(targets)
    manifest={'scope':'seen_development_only','development':c['authorized_development'],
        'outer_oos':'LOCKED','forward_2027':'SEALED','cutoff':c['authorized_development'][-1][1],
        'prices':evidence,'local_quote_volume':'base_volume_times_same_bar_close_proxy',
        'production_reference':'frozen canonical authorized decisions; prior day target replayed at next open; PnL not imported',
        'BASE_resolution_source':str(baseline),'BASE_rows_resolved':sum(r['original_target_asset']=='BASE' for r in targets),
        'targets_first':targets[0]['date'],'targets_last':targets[-1]['date'],'targets_rows':len(targets),
        'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir() if p.is_file()}}
    (destination/'local_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'assets':len(prices),'target_rows':len(targets),'target_end':targets[-1]['date'], 'cutoff':manifest['cutoff']}))

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();freeze_local(a.repo,a.out)
