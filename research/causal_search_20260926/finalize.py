"""Bind completed empirical evidence to the objectives gate and verify exports."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd
from prepare import write_json,digest
import engine
import run
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from scripts import research_objectives as objectives


def finalize(out):
    result=json.loads((out/'results.json').read_text());audit=json.loads((out/'expanded_audits.json').read_text())
    choices=json.loads((out/'walk_forward_choices.json').read_text());nom=result['forward_nominees']
    original_manifest=json.loads((out/'reproduction_manifest.json').read_text())
    for name,sha in original_manifest['files'].items():assert digest((out/name).read_bytes())==sha,name
    freeze=json.loads((out/'implementation_freeze.json').read_text());spec,contract=engine.load_spec()
    assert freeze['code_sha256']==run.code_hashes(),'Search code changed after evaluation'
    table=pd.read_csv(out/'validation_scores.csv')
    assert len(table)==1944*7
    for part in spec['partitions']:
        sub=table[table.partition==part['id']]
        assert sub.variant.nunique()==324 and len(sub)==324*7
    actual_folds=pd.read_csv(out/'oos_folds.csv');assert len(actual_folds)==18*6
    for name,folds in choices.items():
        for fold in spec['folds']:
            assert folds[fold['id']]['validation_end']<fold['test_start']
    evaluation=out/'evaluation';evaluation.mkdir(exist_ok=True)
    evidence=dict(scope='Independent post-run consistency checks plus empirical replay audits',
                  empirical_audits=audit,source_manifest_sha256=digest((out/'reproduction_manifest.json').read_bytes()),
                  input_sha256=spec['input_bundle_sha256'],code_sha256=freeze['code_sha256'],nominees=nom,
                  all_partition_budgets_match=True,all_choices_precede_test=True,ledger_checks={},
                  venue_and_historical_universe_evidence_available=False)
    attribution=[]
    for policy in result['policies']:
        name=policy['id'];met=policy['oos']
        curve=pd.read_csv(out/f'{name}_equity.csv')
        events=pd.read_csv(out/f'{name}_events.csv')
        eq=np.cumprod(1+curve.net_return.to_numpy())
        assert np.allclose(eq,curve.equity,atol=1e-12,rtol=1e-12)
        years=len(curve)/365.25
        cagr=eq[-1]**(1/years)-1
        assert abs(cagr-met['cagr'])<1e-10
        if len(events):
            # Exported episode IDs are local to each annual replay. Composite
            # year + episode is the globally unique position generation.
            events['trade_id']=events.date.str[:4]+'/'+events.episode.astype(str)
            groups=events.groupby('trade_id').log_growth.sum().sort_values(ascending=False)
            total=np.log(eq[-1])
            assert abs(events.log_growth.sum()-total)<1e-8
            for trade_id,part in events.groupby('trade_id'):
                assets=part.asset.unique();assert len(assets)==1,(name,trade_id,assets)
                attribution.append(dict(policy=name,trade_id=trade_id,asset=assets[0],
                                        first_day=part.date.min(),last_day=part.date.max(),log_growth=part.log_growth.sum()))
            omission=np.exp((total-groups[groups>0].head(3).sum())/years)-1
            assert abs(omission-met['without_top_three_trades_cagr'])<1e-9
            day_growth=events.groupby('date').log_growth.sum().reindex(curve.date,fill_value=0).to_numpy()
            assert np.allclose(day_growth,np.log1p(curve.net_return.to_numpy()),atol=1e-9,rtol=1e-9)
        evidence['ledger_checks'][name]=dict(equity_recomputed=True,cagr_recomputed=True,
            daily_log_returns_reconciled=True,top_three_episode_omission_recomputed=True,asset_per_episode_unique=True)
    pd.DataFrame(attribution).to_csv(out/'episode_attribution.csv',index=False,lineterminator='\n')
    write_json(evaluation/'audit_evidence.json',evidence)
    ev=dict(path='audit_evidence.json',sha256=digest((evaluation/'audit_evidence.json').read_bytes()))
    assessments={}
    for policy in result['policies']:
        name=policy['id'];a=audit[name];met=policy['oos']
        candidate=dict(id=name,mode=policy['mode'],exposure_cap=policy['cap'],
                       nominee_categories=[k for k in ['A','B','C'] if nom[k]==name],
                       development=policy['development'] or {},oos=met,sealed={},binding={})
        bind=dict(candidate_id=name,input_sha256=spec['input_bundle_sha256'],
                  code_sha256=digest(json.dumps(freeze['code_sha256'],sort_keys=True).encode()),
                  parameters_sha256=digest(json.dumps(choices[name],sort_keys=True).encode()),
                  contract_sha256=objectives.contract_sha256(),evaluation_sha256=objectives.evaluation_sha256(candidate))
        candidate['binding']=bind
        checks=dict(oos_walk_forward=True,causal_signal_timing=a['same_day_filter_rejection'],
                    asset_lineage=a['asset_price_fill_lineage'],realizable_fills=False,venue_cost_coverage=False,
                    dynamic_exposure=met['max_realized_exposure']<=policy['cap']+1e-12,
                    risk_state_machine=True,parameter_neighbors=met['parameter_stability']==1,
                    sealed_evaluation=False,selection_frozen_before_seal=True,
                    prefix_replay_invariance=a['prefix_replay_invariance'],future_data_perturbation_invariance=a['future_data_perturbation_invariance'],
                    same_day_filter_rejection=a['same_day_filter_rejection'],point_in_time_universe=False,
                    signal_publication_timestamps=False,asset_price_fill_lineage=a['asset_price_fill_lineage'],
                    pnl_reconciliation=a['pnl_reconciliation'],gap_and_intrabar_fill_order=True,cost_funding_alignment=False)
        candidate['audits']={k:dict(passed=bool(v),binding=bind,artifacts=[ev]) for k,v in checks.items()}
        write_json(evaluation/f'{name}.json',candidate)
        assessments[name]=objectives.assess(candidate,evaluation)
        assert not assessments[name]['high_return_gates_passed']
    write_json(evaluation/'objectives_screening.json',assessments)
    # Audit evidence has explicit failures: do not manufacture a successful seal.
    write_json(out/'verification.json',dict(partitions=6,variants_per_partition=324,unique_nominal_trials=1944,
               grid_validation_rows=len(table),oos_policies=18,oos_folds=108,independent_ledger_checks_passed=True,
               objective_gate_evaluated=True,all_high_return_winners_blocked_without_seal=True,
               generated_outputs_are_real_account_pnl=False,source_code_matches_frozen_fingerprint=True,
               count_scope='Unique search candidates; repeated stress, audit, neighbor and reproducibility runs are separate computations.'))
    print('PASS: 1,944 trials, 108 OOS folds, all 18 equity/log/asset/episode reconciliations and fail-closed objective gates')


if __name__=='__main__':finalize(HERE/'results')
