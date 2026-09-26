"""Verify a second OOS replay and deterministic independent grid spot checks.

The six full grid partitions may be reused only through the runner's exact
implementation fingerprint. This is not described as a second fresh full grid.
Use an empty --cache to reproduce the entire search from raw frozen inputs.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import numpy as np
import pandas as pd
import engine
import run
from prepare import digest,write_json

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=engine.ROOT/'scratch/causal_reproduction')
    parser.add_argument('--cache',type=Path,default=engine.ROOT/'scratch/causal_search_post_exit_cache')
    args=parser.parse_args();reference=HERE/'results'
    if args.out.exists():raise FileExistsError('Use a new output directory for an independent replay')
    subprocess.run([sys.executable,str(HERE/'run.py'),'--out',str(args.out),'--cache',str(args.cache)],check=True,cwd=engine.ROOT)
    original=json.loads((reference/'reproduction_manifest.json').read_text())
    repeated=json.loads((args.out/'reproduction_manifest.json').read_text())
    assert original['search_fingerprint']==repeated['search_fingerprint']
    assert set(original['files'])==set(repeated['files'])
    byte_identical=0;order_only=[]
    for name,sha in original['files'].items():
        assert digest((reference/name).read_bytes())==sha
        if digest((args.out/name).read_bytes())==sha:
            byte_identical+=1
        else:
            # JSON caches sort object keys. A fresh grid retains insertion order,
            # so only the exported validation table's row/column order may vary.
            assert name=='validation_scores.csv',f'Core result changed: {name}'
            canonical=lambda path:pd.read_csv(path).sort_values(['partition','variant','window']).reset_index(drop=True).sort_index(axis=1)
            pd.testing.assert_frame_equal(canonical(reference/name),canonical(args.out/name),check_exact=True)
            order_only.append(name)
    spec,_=engine.load_spec();market=engine.load_market();checks=[]
    # Fixed locations in the frozen grid; never selected for favorable results.
    for part in spec['partitions']:
        cached=json.loads((args.cache/(part['id']+'.json')).read_text())['records']
        for index in [0,162,323]:
            p=spec['variants'][index]
            nominal=engine.simulate(market,p,part['cap'],end='2025-12-31')
            doubled=engine.simulate(market,p,part['cap'],end='2025-12-31',cost_multiplier=2)
            delayed=engine.simulate(market,p,part['cap'],end='2025-12-31',delay=1)
            fresh=run.metric_windows(nominal,doubled,delayed,spec)
            for window,metrics in fresh.items():
                for key,value in metrics.items():
                    if key=='parameter_stability':continue # depends on the entire neighboring grid
                    assert np.allclose(value,cached[p['id']][window][key],rtol=1e-12,atol=1e-12),(part['id'],p['id'],window,key)
            checks.append(dict(partition=part['id'],grid_index=index,variant=p['id'],scenarios=3,windows=7,passed=True))
    write_json(reference/'reproducibility_verification.json',dict(
        all_core_results_identical=True,core_file_count=len(original['files']),
        bitwise_identical_file_count=byte_identical,order_only_differences=order_only,
        independent_oos_replay=True,full_grid_repeated=False,
        grid_cache='Exact input/code/contract fingerprint verified by runner; 18 fixed grid cases independently recomputed',
        spot_checks=checks,grid_scenario_replays=54,
        implementation_fingerprint=original['search_fingerprint'],
        replay_command=[sys.executable,str(HERE/'run.py'),'--out',str(args.out),'--cache',str(args.cache)]))
    print(f"PASS: {byte_identical} bitwise-identical files, {len(order_only)} exact order-normalized tables; 54 fresh grid scenario replays")


if __name__=='__main__':main()
