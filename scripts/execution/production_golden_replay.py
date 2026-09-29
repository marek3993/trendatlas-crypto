"""Offline Production Core replay with fixed metadata and no tolerance inflation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.production import build_current_strategy_snapshot as builder
from scripts.production.validate_current_strategy_snapshot import validate_production_payloads


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    adapter=builder._resolve_adapter(builder._resolve_current_strategy_model(ROOT))
    inputs=adapter.load_inputs(root=ROOT)
    timeseries=adapter.build_timeseries(inputs)
    snapshot=builder._build_snapshot(generated_at_utc='2026-09-29T00:00:00Z',adapter=adapter,
        inputs=inputs,timeseries=timeseries,build_command='golden-replay',git_commit='frozen-input')
    diagnostics=builder._build_diagnostics(generated_at_utc='2026-09-29T00:00:00Z',adapter=adapter,
        inputs=inputs,timeseries=timeseries,validation={'status':'passed','errors':[],'warnings':[],'checks':{}})
    validation=validate_production_payloads(snapshot=snapshot,timeseries=timeseries,diagnostics=diagnostics,adapter=adapter,inputs=inputs)
    if validation['status']!='passed': raise RuntimeError(str(validation['errors']))
    # Exact source computations, including all historical returns, weights and rounding.
    result={'snapshot':snapshot,'timeseries':timeseries.to_json(orient='split',date_format='iso',double_precision=15)}
    rendered=json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False).replace(str(ROOT),'<ROOT>')
    args.output.write_text(rendered+'\n')

if __name__=='__main__': main()
