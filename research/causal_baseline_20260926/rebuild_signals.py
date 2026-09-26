"""Offline pinned selection replay and corrected economic lineage.

Uses only pure functions from the captured strategy code. Never invokes mains,
refresh entrypoints, exchange clients or production writers.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

def compare(left, right):
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        return {"schema_or_length": True}
    diffs = {}
    for c in left:
        if pd.api.types.is_numeric_dtype(left[c]) and pd.api.types.is_numeric_dtype(right[c]):
            # Rolling variance near zero differs across pandas builds at ~7e-9
            # after square root. Return/price/equity tolerances remain stricter.
            same = np.isclose(left[c], right[c], atol=1e-8 if c == "rolling_vol_30d" else 1e-9, rtol=1e-12, equal_nan=True)
        else:
            same = left[c].fillna("").astype(str).eq(right[c].fillna("").astype(str))
        if not same.all():
            diffs[c] = int((~same).sum())
    return diffs

def main(root, out):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root/"scripts"))
    sys.path.insert(0, str(root/"src"))
    import phase60_selective_restore_robustness as p60
    import phase63_btc_participation_overlay as p63
    import phase66e_probation_governance as gov
    import phase66g_production_candidate_live as p66
    import phase68g_portfolio_exposure_leverage_validation as lev
    from approved_strategy_net_export_helper import NetCostExportConfig
    from scripts.production.strategy_adapters import phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter as etf
    from scripts.production.strategy_adapters import phase68g_btc_persistence_10d_early_risk_075_adapter as persistence
    from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import Phase68g66g1p25xCandidateAdapter
    import dev_only_phase68g_etf_flow_impulse_probe as probe
    import dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity as cooldown
    spec = importlib.util.spec_from_file_location("causal", REPO/"scripts/production/causal_performance.py")
    causal = importlib.util.module_from_spec(spec); sys.modules[spec.name] = causal; spec.loader.exec_module(causal)
    out.mkdir(parents=True, exist_ok=True)
    # Reproduce original, including its defects, before correcting anything.
    adapter = etf.Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter()
    original_inputs = adapter.load_inputs(root=root)
    reproduced = adapter.build_timeseries(original_inputs)
    original = pd.read_csv(root/"outputs/production/current_strategy_timeseries.csv")
    snapshot = json.loads((root/"outputs/production/current_strategy_snapshot.json").read_text())
    original_diff = compare(original, reproduced)
    metrics_equal = adapter.build_snapshot_metrics(original_inputs,reproduced) == snapshot["metrics"]
    original_check = {"rows":len(original),"differences":original_diff,"snapshot_metrics_match":metrics_equal,
                      "rolling_vol_max_abs_difference":float((original.rolling_vol_30d-reproduced.rolling_vol_30d).abs().max()),
                      "tolerance":"absolute 1e-9; rolling_vol_30d 1e-8; relative 1e-12",
                      "passed":not original_diff and metrics_equal}
    (out/"original_reproduction.json").write_text(json.dumps(original_check,indent=2)+"\n",encoding="utf-8",newline="\n")
    if not original_check["passed"]:
        raise ValueError("Original pinned adapter failed reproduction: " + str(original_check))

    # Reconstruct the pinned core only, not its research grid.
    assets = {s:p60.load_ohlcv_csv(root/"data/ohlcv"/(s+"_1d.csv")) for s in p60.ALL_SYMBOLS}
    macro = p60.load_macro_csv(root/"data/macro/global_liquidity_weekly.csv")
    tables = p60.build_daily_tables(assets,macro,p60.ALL_SYMBOLS)
    selection = p60.select_daily_top1_variant(tables,p60.PINNED_PHASE60_DEPENDENCY_MODEL_KEY)
    base = p60.run_daily_model(selection,tables,p60.PINNED_PHASE60_DEPENDENCY_MODEL_KEY)
    frozen_base = pd.read_csv(root/"outputs/phase60_selective_restore_robustness/phase60_restore_trx_sol_base_paper.csv")
    rebuilt_base = base.reset_index(); rebuilt_base['ts']=rebuilt_base.ts.dt.strftime('%Y-%m-%d')
    base_check = compare(frozen_base[[c for c in rebuilt_base if c in frozen_base]], rebuilt_base[[c for c in rebuilt_base if c in frozen_base]])
    (out/"raw_rebuild_check.json").write_text(json.dumps({"phase60_differences":base_check},indent=2)+"\n",encoding="utf-8",newline="\n")
    # All downstream indicator inputs are derived from this raw replay.
    base_path=out/"core_base.csv"; base.to_csv(base_path,index=True,lineterminator="\n")
    base_input=p63.merge_inputs(p63.load_base_strategy(base_path),p63.load_btc_prices(root/"data/ohlcv/BTCUSDT_1d.csv"))
    config=p63.parse_variant_key(gov.CURRENT_WINNER_KEY)
    phase63=p63.simulate_variant(base_input,config)
    # The BASE branch receives today's core return, hence today's core holding.
    # Shifting the position label again labels a different asset on switch days.
    phase63.loc[phase63.executed_regime.eq("BASE"),"executed_position"] = base.selected.reindex(phase63.index)
    phase63_path=out/"core_overlay.csv"; phase63.to_csv(phase63_path,index=True,lineterminator="\n")
    overlay_config=gov.OverlayConfig()
    baseline=gov.load_baseline_paper(phase63_path,overlay_config)
    winner=json.loads((root/"outputs/phase66g_production_candidate_live/phase66g_manifest.json").read_text())
    removed=set(winner["removed_assets"])
    asset_strategies={}
    for symbol in sorted(assets):
        coin=symbol[:-4]
        if coin=="BTC" or coin in removed: continue
        candidate=assets[symbol][["close"]].rename(columns={"close":"candidate_close"})
        asset_strategies[coin]=gov.build_asset_strategy(baseline,candidate,overlay_config,coin)
    governance,decisions,leaderboard=gov.simulate_governance_strategy_probation(baseline,asset_strategies,gov.GovernanceConfig(**winner["winner_profile"]))
    governance=governance.reset_index().rename(columns={"index":"date", "ts":"date", "day":"date"})
    lineage=pd.DataFrame({"date":base.index,"base_asset":base.selected.values})
    governance["economic_asset"]=causal.economic_assets(governance,lineage)
    governance.to_csv(out/"governance_lineage.csv",index=False,lineterminator="\n")
    decisions.to_csv(out/"universe_decisions.csv",index=False,lineterminator="\n")
    # Gross means price return. The old base_ret carried Phase60 net transaction
    # costs into the alleged gross series; these are no longer charged twice.
    closes=pd.concat({s[:-4]:f.close.pct_change() for s,f in assets.items()},axis=1)
    gross=[]
    for row in governance.itertuples():
        gross.append(0.0 if row.economic_asset=="CASH" else float(closes.loc[row.date,row.economic_asset]))
    portfolio=pd.DataFrame({"date":governance.date,"base_ret":gross,
                            "portfolio_held_asset":governance.economic_asset,
                            "is_exposed":governance.economic_asset.ne("CASH")})
    trend=p66.build_trend_barometer_history(baseline,overlay_config).reset_index().rename(columns={"ts":"date", "index":"date"})
    wrapped=lev.build_validation_wrapper(portfolio,trend,pd.DataFrame(),
        lev.ValidationVariant("phase68g_66g_1p25x_candidate",1.25),0.12,10.0,0.10,20,-0.08,-0.04)
    cfg=NetCostExportConfig(annual_borrow_cost=0.12,tradable_transition_slippage_bps=10.0,taker_fee_bps=4.5,maker_fee_bps=1.5)
    benchmark=pd.DataFrame({"date":assets["BTCUSDT"].index,"btc_close":assets["BTCUSDT"].close.values})
    static=Phase68g66g1p25xCandidateAdapter().build_timeseries({"paper_df":wrapped,"benchmark_df":benchmark,"config":cfg})
    pf,_,cost_model=persistence._prepare_baseline_frame_from_timeseries(static)
    pv=persistence._build_variant_state(pf,cost_model)
    durable=persistence._build_active_timeseries({"canonical_baseline_timeseries":static,"selected_variant_frame":pv["selected_variant_frame"]})
    bf,_=etf._normalize_baseline_frame_from_timeseries(durable)
    full=probe.build_full_history_frame(bf,probe.load_etf_panel(root/"outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel/btc_etf_flow_daily_panel.csv"),probe.load_btc_frame(root/"data/ohlcv/BTCUSDT_1d.csv"))
    state,_=cooldown.build_cooldown_state_machine(full,15)
    signals=pd.DataFrame({"signal_data_day":state.index.strftime("%Y-%m-%d"),
                         "selected_asset":state.probe_held_asset.map(causal.asset),
                         "target_exposure":state.probe_effective_leverage.values,
                         "source_file":"signal_lineage.csv", "source_row":np.arange(len(state))+2})
    signals.index=range(len(signals))
    signals.loc[signals.selected_asset.eq("CASH"),"target_exposure"]=0.0
    signals["signal_available_at"]=(pd.to_datetime(signals.signal_data_day,utc=True)+pd.Timedelta(days=1,hours=12)).astype(str)
    signals["availability_basis"]="assumed_D_plus_1_12UTC_no_complete_historical_runtime_log"
    observed = {}
    for path in sorted((root/"outputs/execution/production_runs").rglob("production_run_manifest.json")):
        run = json.loads(path.read_text())
        stage = run.get("stages", {}).get("VALIDATE_PRODUCTION_CORE", {})
        day, at = run.get("target_closed_day"), stage.get("finished_at")
        if day and at and stage.get("status") == "PASSED" and pd.Timestamp(at) > pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1):
            if day not in observed or at < observed[day][0]:
                observed[day] = (at, path.relative_to(root).as_posix())
    signals["availability_source_file"] = "documented_proxy_schedule"
    for day, (at, source) in observed.items():
        mask = signals.signal_data_day.eq(day)
        signals.loc[mask, "signal_available_at"] = at
        signals.loc[mask, "availability_basis"] = "observed_original_build_validation_counterfactual_schedule"
        signals.loc[mask, "availability_source_file"] = source
    # Preserve actual observed availability for the final published data day.
    mask=signals.signal_data_day.eq(snapshot["closed_day"])
    signals.loc[mask,"signal_available_at"]=snapshot["generated_at_utc"]
    signals.loc[mask,"availability_basis"]="observed_published_build_completion"
    signals.loc[mask,"availability_source_file"]="outputs/production/current_strategy_snapshot.json"
    state.reset_index(drop="date" in state.columns).to_csv(out/"signal_lineage.csv",index=False,lineterminator="\n")
    signals.to_csv(out/"signals.csv",index=False,lineterminator="\n")
    print(json.dumps({"original_reproduction":original_check,"raw_core_differences":base_check,"latest_signal":signals.iloc[-1].to_dict()}))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    main(a.root.resolve(),a.out.resolve())
