"""Offline numeric investigation; independent oracle, never a production signal.

The Welford experiment mirrors the scalar recurrence in pandas 3.0.3
pandas/_libs/window/aggregations.pyx; FMA is its sole experimental variable.
Do not use the emulation or the Decimal oracle in execution/strategy code.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import sys


def oracle(returns, window, precision=80, binary_input=False):
    """Independent centered two-pass Decimal calculation, fresh for each window."""
    result = []
    with localcontext() as context:
        context.prec = precision
        annualizer = Decimal('365.25').sqrt()
        values = [Decimal.from_float(float(v)) if binary_input else Decimal(str(v))
                  for v in returns]
        values = [Decimal(0) if v.is_nan() else v for v in values]
        for i in range(len(values)):
            if i + 1 < window:
                result.append(None)
                continue
            sample = values[i + 1 - window:i + 1]
            mean = sum(sample, Decimal(0)) / window
            variance = sum(((v - mean) ** 2 for v in sample), Decimal(0)) / window
            std = variance.sqrt()
            result.append({'mean': mean, 'variance': variance, 'std': std,
                           'volatility': std * annualizer,
                           'sharpe': mean / std * annualizer if std else None})
    return result


def emulate_welford(values, window, fused):
    """Controlled FMA experiment; fixed row/operation order and recompute rule."""
    count = mean = moment = add_compensation = remove_compensation = 0.0
    unstable = False
    result = []

    def update(value, remove):
        nonlocal count, mean, moment, add_compensation, remove_compensation, unstable
        if math.isnan(value):
            return
        previous = moment
        count += -1 if remove else 1
        if not count:
            mean = moment = 0.0
            unstable = False
            return
        compensation = remove_compensation if remove else add_compensation
        previous_mean = mean - compensation
        corrected = value - compensation
        delta = corrected - mean
        compensation = delta + mean - corrected
        if remove:
            remove_compensation = compensation
            mean -= delta / count
        else:
            add_compensation = compensation
            mean += delta / count
        left, right = value - previous_mean, value - mean
        if remove:
            left = -left
        moment = math.fma(left, right, moment) if fused else moment + left * right
        unstable |= previous * (sys.float_info.epsilon * 1000) > moment

    for i, value in enumerate(values):
        if i >= window:
            update(values[i - window], True)
        update(value, False)
        if i == 0 or unstable:
            count = mean = moment = add_compensation = remove_compensation = 0.0
            for item in values[max(0, i - window + 1):i + 1]:
                update(item, False)
            unstable = False
        result.append(moment / count if count >= window else math.nan)
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    default=str).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    import numpy as np
    import pandas as pd
    from scripts.production import build_current_strategy_snapshot as builder
    from scripts.production.canonical_diagnostics import canonical_diagnostic_export, diagnostic_units

    adapter = builder._resolve_adapter(builder._resolve_current_strategy_model(root))
    inputs = adapter.load_inputs(root=root)
    native = adapter.build_timeseries(inputs)
    exported = canonical_diagnostic_export(native)
    values = native['return_net'].tolist()
    data = {'raw_inputs': {}, 'input_frames': {}, 'metrics': {}, 'oracle': {}, 'emulation': {},
            'native_fields': {}, 'old_production_fields': {}, 'threshold_distances': {}}
    paths = dict(inputs['source_paths'])
    universe = json.loads((root/'source_of_truth/production_asset_universe_contract.json').read_text())
    paths['selector'] = root / universe['selector_source']
    for key, path in paths.items():
        if path.is_file():
            data['raw_inputs'][key] = {'path': path.relative_to(root).as_posix(),
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    for key, value in inputs.items():
        if isinstance(value, pd.DataFrame):
            data['input_frames'][key] = {'index_type': str(value.index.dtype),
                'index': [str(x) for x in value.index], 'dtypes': {k:str(v) for k,v in value.dtypes.items()},
                'null_mask_sha256': digest(value.isna().values.tolist()),
                'values_sha256': hashlib.sha256(value.to_csv(lineterminator='\n').encode()).hexdigest()}
    data['days'] = native['date'].tolist()
    data['dtypes'] = {k:str(v) for k,v in native.dtypes.items()}
    data['index'] = [str(v) for v in native.index]
    data['return_hex'] = [float(v).hex() for v in values]
    data['annualization_hex'] = float(np.sqrt(365.25)).hex()
    data['canonical_units'] = diagnostic_units(values)
    data['canonical_csv_sha256'] = hashlib.sha256(exported.to_csv(index=False,lineterminator='\n').encode()).hexdigest()
    for window in (30, 90):
        roll = native['return_net'].rolling(window, min_periods=window)
        mean, var, std = roll.mean(), roll.var(ddof=0), roll.std(ddof=0)
        for key, value in [('mean',mean),('variance',var),('std',std),
                           ('volatility',std*np.sqrt(365.25)),
                           ('sharpe',mean/std.replace(0,np.nan)*np.sqrt(365.25))]:
            data['metrics'][f'{window}_{key}'] = [float(v).hex() for v in value]
        for fused in (False, True):
            emulated = emulate_welford(values,window,fused)
            data['emulation'][f'{window}_{fused}'] = [float(v).hex() for v in emulated]
        for binary in (False,True):
            reference = oracle(values,window,binary_input=binary)
            data['oracle'][f'{window}_{binary}'] = [None if r is None else
                {k:None if v is None else str(v) for k,v in r.items()} for r in reference]
    fields = ('rolling_vol_30d','rolling_sharpe_90d')
    for field in fields:
        data['native_fields'][field] = [float(v).hex() for v in native[field]]
    old = pd.read_csv(root/'outputs/production/current_strategy_timeseries.csv')
    data['old_days'] = old['date'].tolist()
    for field in fields:
        data['old_production_fields'][field] = [float(v).hex() for v in old[field]]
    data['old_return_hex'] = [float(v).hex() for v in old['return_net']]
    # All non-diagnostic columns, not a hand-picked subset of decisions.
    non_diagnostic = [c for c in native if c not in fields]
    data['non_diagnostic_sha256'] = hashlib.sha256(native[non_diagnostic].to_csv(index=False,lineterminator='\n').encode()).hexdigest()
    assert native[non_diagnostic].equals(exported[non_diagnostic])
    # Published decision surfaces. Native enriched surfaces are retained too.
    pairs = [('trend_score','buy_threshold'),('trend_score','trend_activation_threshold')]
    for left,right in pairs:
        if left in native and right in native:
            data['threshold_distances'][left+'-'+right] = [str(Decimal(str(a))-Decimal(str(b))) for a,b in zip(native[left],native[right])]
    for threshold in (0,1e-9,1,1+1e-9):
        data['threshold_distances']['effective_market_exposure-'+str(threshold)] = [str(Decimal(str(v))-Decimal(str(threshold))) for v in native['effective_market_exposure']]
    enriched = inputs.get('enriched')
    if enriched is not None:
        data['decision_surfaces'] = {
            column: [str(v) for v in enriched[column]]
            for column in enriched
            if any(token in column for token in ('permission','filter','threshold','cooldown','pass','block','persistence'))
        }
        for left,right in [('btc_close','btc_ema10'),('close','btc_ema10')]:
            if left in enriched and right in enriched:
                data['threshold_distances'][left+'-'+right] = [str(Decimal(str(a))-Decimal(str(b))) for a,b in zip(enriched[left],enriched[right])]
        if 'flow_3d_sum_usd' in enriched:
            data['threshold_distances']['flow_3d_sum_usd-500000000'] = [str(Decimal(str(v))-Decimal('500000000')) for v in enriched['flow_3d_sum_usd']]
        data['enriched_columns'] = list(enriched.columns)
    btc = inputs.get('btc_df')
    if btc is not None:
        data['btc_ema_audit'] = {c:[str(v) for v in btc[c]] for c in btc}
    args.output.write_text(json.dumps(data,allow_nan=False),encoding='utf-8')
    print(json.dumps({'rows':len(native),'non_diagnostic_sha256':data['non_diagnostic_sha256'],
                      'canonical_csv_sha256':data['canonical_csv_sha256']}))


if __name__ == '__main__':
    main()
