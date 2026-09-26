# Capacity follow-up — offline research

Base: `f5ecbfd1a35dec62a4482cd1a1aa5181e6790551`. Branch: `codex/capacity-followup-20260927`.

Read REPORT.md and AUDIT.md. This directory does not register production scripts, export dashboard state, load exchange credentials, call order endpoints or change Pi timers. Earlier research is immutable.

The initial protocol was frozen before data acquisition. `engine_data_freeze.json` fixes evaluator, schema, identity notices and normalized market inputs before the current complete run; the first pre-API/OOS attempt and its serialization failure are preserved under attempts/. `results/finalists_frozen.json` fixes all forward finalists and historical walk-forward choices before outer replay.

Python3.12.10 was used. In an isolated Python environment:

```powershell
Set-Location C:/Users/benda/Desktop/ta_capacity_followup
python -m pip install -r research/capacity_followup_20260927/requirements.txt
python -m unittest discover -s research/capacity_followup_20260927 -p test_followup.py -v
python research/capacity_followup_20260927/data_quality.py
python research/capacity_followup_20260927/audit.py
python research/capacity_followup_20260927/verify_saved.py
python research/capacity_followup_20260927/concentration.py
python research/capacity_followup_20260927/render.py
```

Full offline reproduction with the original accepted/rejected API proposals, to a new output directory (no API charge):

```powershell
python research/capacity_followup_20260927/run.py --replay-proposals research/capacity_followup_20260927/results/designer_events.jsonl --output-dir "$env:TEMP/ta-capacity-reproduction"
```

The runner refuses to overwrite a completed development result. Remove neither original evidence nor a failed attempt to obtain a better score. Preserve any failed attempt and identify a correctness reason before rerunning.

Original acquisition/execution commands, **not required when reproducing committed normalized data**:

```powershell
python research/capacity_followup_20260927/data_prepare.py
python research/capacity_followup_20260927/data_finalize.py
python research/capacity_followup_20260927/perpetual_gate.py
python research/capacity_followup_20260927/run.py
```

`data_prepare.py` reads the complete Binance public archive census, validates ZIP checksums and keeps raw downloads in ignored `archive/`. Committed ZIPs contain normalized exact-symbol OHLCV/funding and archive census evidence. Normalized numbers retain12 significant digits; source hashes and paths remain in acquisition.json. Different future archive revisions must never silently replace the frozen inputs. `data_finalize.py` completes the union needed by the one identity-aware PIT eligibility rule.

`DEEPSEEK_API_KEY` or `MRV1_DEEPSEEK_API_KEY` is read only from the process or Windows user's named environment entry. It is never written to evidence. Real calls only send current-origin development metric whitelist and the permitted parameter JSON schema. Responses cannot alter evaluator/data/metrics or generate executable code. Deterministic fallback has the same budget and remains labeled.

Primary100 USD and the four larger accounts are **simulated** capital, not real wallet exposure or real account PnL. USDT is treated as USD at1:1; no depeg FX model. Fractional spot quantity and conservative10 USD minimum notional are explicit assumptions, not historical lot/tick certification. Actual fills use the instrument's own next executable4h open, fixed slippage/fees, a lagged-volume participation limit, partials, TTL and cash reconciliation. This is not a venue-independent or live Hyperliquid capacity certificate.

Every actual trade/mark/funding gap for familyD and every missing historical risk-contract interval is in perpetual_data_gate.json. A present-day authenticated maintenance table cannot authorize a historical liquidation simulation. All four D recipes remain NOT_RUN when that gate fails. No weak strategies are blended into E.

Large ledger evidence is delivered as `results/replay_ledgers.part*.zip`. `ledger_partitions.json` records the original ZIP hash and every unchanged uncompressed member hash; `ledger_archive.py` reads the parts transparently. Original runner output remains a single ignored ZIP; `bundle_ledgers.py` partitions it only for Git hosting, without changing any value.
