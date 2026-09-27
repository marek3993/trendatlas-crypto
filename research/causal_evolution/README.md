# Causal continuous evolution (research only)

This package is isolated from production and starts from origin/main `730b57c1e8815e50def473ad641a1c9db3477bc4`. It does not import the legacy worker's evaluator, weighted fitness, paper equity, return streams or production integrations. The preregistration commit is `b476a8edf6bfdd68936a109a631e44cd85f152ef`.

## Reproduce

```powershell
python -m venv research/causal_evolution/local_state/runtime
research/causal_evolution/local_state/runtime/Scripts/python.exe -m pip install -r research/causal_evolution/requirements.txt
research/causal_evolution/local_state/runtime/Scripts/python.exe -m unittest research.causal_evolution.tests research.causal_evolution.vendor.test_research -v
research/causal_evolution/local_state/runtime/Scripts/python.exe -m research.causal_evolution.cli run --state research/causal_evolution/local_state/synthetic_verified --synthetic --inline-broker
research/causal_evolution/local_state/runtime/Scripts/python.exe -m research.causal_evolution.cli smoke --state research/causal_evolution/local_state/real_smoke
```

The synthetic profile has F spot, 10/6/4, two generations, three seeds, both arms, one origin, real ledger and complete outer/export transitions. All F/G/H/D branches also have independent synthetic causality/ledger regression coverage. Synthetic performance is never financial evidence. Reuse an unchanged state directory to resume; changed evaluator or data hashes are refused.

For a full LOCAL experiment (a separate explicitly labeled research run):

```powershell
research/causal_evolution/local_state/runtime/Scripts/python.exe -m research.causal_evolution.cli run --state research/causal_evolution/local_state/full --inline-broker
```

Do not run this as a replacement for or hidden repeat of the active Pi experiment. Pi runs the same code with a network-denied worker and a separate development-only broker. The key comes from process/user environment locally, or a dedicated encrypted systemd credential on Pi. Never put keys in commands, source, logs or git.

## Frozen design

`evolution_contract.json` and `anti_overfitting_contract.json` are the design authority. The manifest hashes all evaluator, signal, protocol, statistical and raw input files BEFORE real performance. Four islands: F spot, G spot, H spot, D actual Binance USD-M conservative proxy. Never Hyperliquid historical PnL or venue certification. 10 candidates, six Pareto survivors, four mutations; three search seeds; five generations maximum. Deterministic and DeepSeek have equal ceilings. Stops are independent frozen diversity/front stagnation rules, so actual consumed budgets may differ and are reported. Identical computations may be cached; candidate-slot accounting does not disappear.

Initial genes are source-code hypotheses only. The two named G seeds are SMA150 monthly, satellite50%/one alt, confirmation3/hysteresis0 and confirmation7/hysteresis1%. BTC mom90 monthly and breakout120 weekly were previously picked after OOS and remain explicitly contaminated historical hypotheses. CASH is an immutable reference and an available position state, not a fabricated return series.

Nested anchored train starts2020-01-01. Each origin has two120-day validation windows, separated from its training and outer periods by459 excluded days (365 lookback +1 publication +90 maximum holding +3 exit TTL). Both origins' searches finish before any outer opens. Early stop uses expansion of the nondominated front, not a scalar fitness. Fixed epsilon boxes and crowding prefer simpler similar rules.

The fixed90-day holding horizon is a new non-optimized CV constraint; its uncapped ablation is also mandatory. No price stop, TP, ETF flow or cooldown is searched. Every exit still needs actual future bars and participation; material residual after93days invalidates execution. Dust remains valued. Literal BTC SMA200 has its original unbounded holding rule and the same venue/fee/fill model.

Primary OOS curves carry actual cash, quantities, costs, episodes and residuals continuously through2024-2025. Annual rule switches are nominated solely from inner data and frozen before the first outer observation. They create ordinary latency-safe order intents, never a year-end fictitious liquidation/reset. Independently initialized annual diagnostic books are retained and labeled separately from the continuous primary book.

The DeepSeek broker receives only schema-checked development JSON in `mailbox/proposals.sqlite`. It cannot mount the market/result database, datasets, production repository, production credentials, account state or order integration. Worker networking is entirely denied. The response is never code, a command, a tool invocation, or an evaluator/data amendment.

## Continuous operation

Pi state: `/var/lib/trendatlas-research/causal-v1/current`. Dispatcher and worker retain the existing research unit names and dispatcher timer cadence. Production service/timer are only inspected. `OnSuccessJobMode=ignore-requirements`, the admission gate and worker conflict/ordering preserve production priority. Aggregate research CPU quota20%. On this Pi the memory controller is absent: address-space limit768MiB plus `mlockall(CURRENT|FUTURE)` provide the verified fail-closed fallback. Temperature stops75C/restarts below68C; free disk reserve1GiB. A worker activation lasts at most30minutes and saves SQLite FULL-synchronous checkpoints. Whole-cycle active budget24hours, results budget512MiB, API96calls/$1 ceiling. No automatic production promotion.

Public monthly archive ingestion is separate, checksummed, resumable and rate/byte bounded. All historical archive symbols are censused, including ceased ones, not today's exchangeInfo survivors. Only completed months with a7-day publication buffer are eligible; funding is never synthesized. Missing archives/marks/funding remain explicit. Newly observed gaps>2days or discontinuities outside price ratio[0.2,5] quarantine a possible new identity and restart its365-observation admission instead of transferring an old quantity into it.

A successor needs at least30 new closed UTC days, a complete append-only dataset chain, a new experiment ID/fingerprint and the fixed refit date. Quarterly checks do not force new searches: this annual-outer design also requires a newly completed calendar year. The first eligibility date is2027-01-01, possibly delayed by archive publication/resources. Subsequent annual windows roll mechanically, with no schema/budget expansion. Historical outer becomes explicitly seen history in a new cycle; it is never relabeled globally sealed. No same-data rejection-driven successor is allowed.

Prospective observation begins no earlier than2026-09-27 AND the day after actual nominee freeze. Earlier days in the requested forward window are not falsely claimed as prospectively frozen predictions. Forward evaluation lives in a separate database and cannot feed mutations before refit. Missing complete published data means waiting, not an invented result.

## Outputs

`status.json`, `frozen_manifest.json`, `frozen_finalists.json`, `candidate_genes.json`, `mutation_lineage.json`, SQLite results/attempts, development folds, `all_results.csv`, annual/capacity/stress tables, regime attribution, `pareto_front.json`, `equity.csv`, `equity.svg`, `deepseek_proposals.json`, `audit_results.json`, generated `REPORT.md`. The outer result appears in status only after terminal sealing. A/B/C are qualified high-return, robust and Pareto alternatives; D is honest REJECT if none qualify; E is forward observation status.

DSR counts all candidate/neighbor hypotheses plus interrupted attempts and known predecessor counts; prior informal studies are uncountable, so global independence is never claimed. CSCV is retrospective diagnostic only, never the chronological fitting split. Paired stationary block bootstrap uses mean30-day blocks/499replicates; Holm corrects every frozen finalist including failed ones. Low history/trade/diversity power is INCONCLUSIVE, not PASS. This is not advertised as exact Hansen SPA.

Sources: [DSR primary paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf), [PBO primary paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf), [White Reality Check](https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152), [official DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/), [official JSON output](https://api-docs.deepseek.com/guides/json_mode/). API dollars are explicitly the documented peak-rate upper estimate, not a billing-invoice claim.
