# Research audit

## FILES READ

The required order was followed in the user's original checkout:
`source_of_truth/README.md`, `master_state.md`, `chat_roles.md`,
`project_truth.json`, `export_contract.json`, `paths_registry.json`,
`current_issues.md`, `canonical/script_registry.json`, `output_registry.json`,
and `registry_workflow.md`. Large JSON files were additionally inspected by
their production/authority/semantics keys. `AGENTS.md` and the user-approved
`source_of_truth/research_objectives_contract.json` were read.

From source commit `d3be15dbd4da8be1f97cb526dc8cacf8cd7d0e75`, the archaeology
engine, contract, source-reconstruction report and audit were read. Old stored
performance was context only, never a new strategy/evaluator input.
`examples/download_4h_history.py` and `examples/download_funding_binance.py`
were inspected for raw-data lineage. Local raw CSV schemas/coverage were
inspected but the scored input is a new checksummed public archive freeze.

Primary external documentation actually consulted:

- https://github.com/binance/binance-public-data
- https://api-docs.deepseek.com/guides/json_mode/
- https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data
- https://www.binance.com/en/support/announcement/detail/1e89a9ca957c4b0ca7502e60b993e201

No Pi runtime work was planned or performed. No exchange account endpoint,
order endpoint, wallet key or scheduler was accessed.

## SOURCE OF TRUTH

SSOT remains authoritative for current production and its boundaries. The
latest user request authorizes a new research decision engine, not replacement
of production artifacts. This task is class B+D. The new `contract.json` was
written and validated before strategy implementation or performance search.
It supersedes only this research experiment's definitions. The original
production and archaeology contracts remain byte-identical.

Raw Binance archive ZIPs and their official SHA256 checksums define market
observations. `cohort.json` defines the ex-ante December2020 cohort; the same
admission/liquidity contract serves every model. `listing_evidence.json`
records actual first archived traded minutes; these are distinguished from
unverified administrative listing announcements. `venue_notices.json`
contains the source-linked EOS publication and effective times. No A-token
return is spliced into EOS.

The packaged evidence contains 2,090 downloaded archives whose bytes were
independently rehashed against both saved metadata and the official checksum
string. All four packaged ZIPs (raw evidence, normalized inputs and two
superseded runs) passed CRC checks. The normalized input hash is
`ed48645dcd3ddbbe6efbe21220ba891e518ab8b1faf38007368df2596324da4b`.

`results/*` are non-authoritative simulated spot research results. They do not
describe real wallet exposure or real-account PnL.

## Exact root cause / contract impact

The archaeology finding requires replacing the decision rules and forbidding
legacy label/return mismatches. Old synthetic BASE/PnL wrappers, same-day PnL
filters and zero-filled cross-sectional ranks cannot enter this new path.
The new decision functions return only a concrete spot pair and 0/1 exposure;
the ledger computes that pair's PnL independently.

The old daily proxy-data contract could not substantiate an executable venue
test. This research adds official spot 4h quote-volume/OHLC, timestamped
contract funding as a separate dataset, first-minute evidence, a delisting
notice, publication latency, size/capacity enforcement and explicit venue
gates. Perpetual scoring remains BLOCKED: funding alone is insufficient without
matched mark/trade prices and historical margin/liquidation evidence. No
synthetic perpetual or short result is reported.

`ledger.py` extends the asset-resolved archaeology engine. `ledger_changes.diff`
shows exact edits: configurable research spot costs, zero spot funding,
timestamped 4h fill/availability, annual exit on only the final bar, fixed units
between changes, participation bounds including exits, correct fractional
holding duration, delay of a forced-flat first order, and UTC-daily Sharpe aggregation. Original accounting
primitives and complete-episode reconciliation are retained. A parity test
requires the original and extended engine to agree on the same daily scenario
and cost model to 12 decimal places.

Only new files under `research/new_strategy_20260926/` are changed. Production
infrastructure, dashboard, planner, Hyperliquid integration, accounts, timers,
reconciliation, SSOT, canonical registries, `data/*` and `outputs/*` are not
patched. The original dirty checkout remains untouched; work is in a separate
worktree and branch based on the supplied commit.

## Regression tests added

`test_framework.py`: 21 passing tests cover contract/budget, parent daily
ledger parity, own-asset payoff isolation, synthetic-label rejection, D+1
04:00 fill after 00:01 availability, adverse two-sided fills, episode log-PnL
reconciliation, no spot funding/leverage/shorts, capacity rejection, missing
exit quote rejection, no future-asset zero-fill/rank impact, slow confirmation,
strict JSON/type/key validation, OOS rejection at the designer boundary,
deterministic mutations, correct drawdown direction in Pareto, one annual
close exit, future-price ledger invariance, doubled costs and Unicode URLs.
Additional regressions verify that the delayed-fill stress also delays the
initial forced-flat entry, the December cohort cannot authorize a preformation
trade, and known unavailable assets are excluded BEFORE liquidity ranking.

`audit.py` passed on 13 distinct frozen configurations: prefix and future-data
perturbation invariance, unavailable-symbol rank invariance, 402 actual fills,
201 complete episodes, source/price/availability checks, all 60 population
transitions, all 330 development trials' temporal scopes, and nominee freeze
before OOS access. Exact machine evidence: `causality_audit.json`.

The final A/B/C and aggressive-diagnostic slots all nominate the same config.
Its separately checked adjacent neighbors are 5/5 executable but only 2/5
qualify; median validation CAGR is negative. Parameter stability is REJECT.
Nominees are not replaced after this unfavorable result.

## Forbidden old path checked

- Strategy/proposer modules have an AST import allowlist. They cannot import
  production/exchange/order modules or arbitrary research-paper loaders.
- The only scored market input is `market_inputs.zip`, with a frozen hash;
  members are raw spot OHLCV/quote-volume and separate real funding events.
- No `*_paper.csv`, historical CAGR, model equity, BASE/synthetic stream,
  authority snapshot or production return path is consumed by new decisions.
  The acquisition script's unrelated `BASE` constant is only the public
  archive URL. The `BASE` instrument regression test requires rejection.
- Negative or >1 exposure is rejected by the spot ledger. Missing actual held
  prices fail closed; the last observed price is never a clairvoyant delist exit.
- Liquidity ranks mask missing assets. Pareto maximizes return and minimizes
  positive loss magnitude; worse drawdown cannot receive a positive reward.
- DeepSeek accepts only validated parameter JSON and receives development
  whitelist fields. No code execution, tools, file paths, OOS or sealed inputs.
  Neither supported DeepSeek environment key was available: 0 API calls,
  deterministic fallback actually used in all 45 mutation rounds.
- No full refresh, deployment, merge, timer operation, live order or account
  command was run. The runner verifies 3,237 protected files unchanged.

## Validation commands and results

From `C:/Users/benda/Desktop/ta_new_strategy`:

```powershell
python -W ignore research/new_strategy_20260926/test_framework.py
python -u -W ignore research/new_strategy_20260926/run.py
python -W ignore research/new_strategy_20260926/audit.py
python -W ignore research/new_strategy_20260926/extra_validation.py
python -W ignore research/new_strategy_20260926/render.py
git diff --cached --check
```

The final real search took 319.06 seconds, recorded in `results/receipt.json`:
330 unique origin-specific
search evaluations, 60 generations, 86 neighbor evaluations, 36 ablations and
12 OOS family/fold evaluations. Reference stresses and five final-nominee
neighbor replays were then completed without reselection. Rejected execution
paths remain rejected; there is no selection of only successful OOS years.

Matplotlib is used from the already available task-specific temporary library
directory. No project/global environment was modified. The exact successful
render command was:

```powershell
python -W ignore -c "import sys,runpy,numpy,pandas;sys.path.insert(0,'research/new_strategy_20260926');sys.path.append('C:/Users/benda/AppData/Local/Temp/ta-archeology-plot-deps');runpy.run_path('research/new_strategy_20260926/render.py',run_name='__main__')"
```

## Attempts and evidence limits

Acquisition initially hit a Unicode symbol URL encoding error after the archive
census. The URL encoder was fixed and checksummed cached downloads were reused.
No strategy outcomes existed at that stage. One explicit development smoke
replay of the already specified A baseline verified runtime; it is the same
configuration included in the 330-trial search, not an extra selected hypothesis.
The first report commands encountered an import-path and a duplicate-dictionary
key issue; these were report-only fixes. Later correctness review required two
explicitly archived replay corrections:

1. The shifted target stream alone did not delay an initial forced-flat fold
   entry when the prior target was already long. The stress now delays that
   new order by the additional bar. The first complete run, its code and
   results remain in `attempts/before_initial_fill_delay_fix.zip`.
2. The December2020 volume cohort must not authorize trades before that month
   has closed and its publication latency elapsed. Signals before the
   2020-12-31 20:00 bar are now inadmissible; first possible fill is 2021-01-01
   04:00. Known EOS unavailability is also applied before daily liquidity
   ranking, in addition to intraday admission. The second complete run and its
   code remain in `attempts/before_cohort_boundary_fix.zip`. Its saved top-level
   report was still from the first run; that attempt's machine ledgers and
   receipt, not that stale report, define its computations.

All three complete searches use the same original contract, grids, costs,
cohort, seed, per-origin budget and nomination rules. Corrections were to
causality/execution implementation, not favorable parameter tuning. Each
corrected run starts a new code/data freeze and repeats the full search and
OOS. Final code and inputs remain frozen throughout the accepted run.
`attempts/attempt_summary.json` records all attempted trial counts and their
candidate overlap. The two superseded 330-trial runs are explicitly disclosed;
the final 330 evaluations are not represented as the only computations done.
No outcome of a discarded run is counted as independent validation.
There were 990 completed search-trial calls across the three attempts, with
341 distinct (origin, configuration) pairs and 319 shared by all three.
The final corrected fitness path automatically generated 11 pairs absent
from the earlier attempts, within the unchanged 330-evaluation per-run budget.
No extra generations or manual outcome-driven parameter changes were added.

The cohort is bounded and excludes post-2020 listings by design. Spot costs and
slippage remain explicit assumptions rather than historical personal fee tiers
or full order-book reconstruction. First traded minutes do not prove a complete
history of every administrative listing notice. Perpetual and short economics
are not tested. Previously inspected history is not retrospectively sealed.
Prospective data beginning 2026-09-27 have not been opened; no successful
validated replacement can be claimed from this run.

The 330 configurations are origin-specific evaluations, not 330 statistically
independent hypotheses. In particular B's `lookback` field is inactive when
`blend=true`; equivalent signal rules may recur. All are retained in the trial
ledger rather than claiming extra independent evidence. NAV is denominated in
USDT; the USD capacity convention assumes stablecoin parity.

## Exact files changed / exact git add list

All changed paths are listed individually in `GIT_ADD.txt`. Raw download cache
files are ignored; `archive_evidence.zip` preserves official ZIPs/checksum
metadata. `market_inputs.zip` is the scored normalized input. Both are research
artifacts, not changes to generated production data.
`artifact_manifest.json` hashes every staged research artifact except itself;
Git records the manifest's own bytes. The staged diff contains only the new
research directory. There are no changes to ancestor archaeology files.

```powershell
git add -f --pathspec-from-file=research/new_strategy_20260926/GIT_ADD.txt
```

`-f` is necessary because the repository ignores ZIP archives. It applies only
to the exact reviewed research paths. Research `.gitattributes` preserves bytes
and recognizes CRLF line endings for whitespace checks.

## Commit message

`research: run causal replacement strategy evolution with venue data gates`

## Commit hash

The final task response reports the created commit and verified remote push.
The commit cannot contain its own hash. No merge or deployment is authorized.
