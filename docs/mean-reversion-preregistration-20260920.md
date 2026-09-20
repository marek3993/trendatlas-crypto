# Mean-reversion preregistration — before implementation

Base: e4929701ed4f3239ace1c92a7eb91c1ab113f2fb. New family:
`btc_short_horizon_long_only_mean_reversion`; study `btc_short_mean_reversion_v1_20260920`.

The complete frozen research contract is
`research_os/dev_only/mean_reversion/CONTRACT.md`; machine-readable domains and
budget are in `research_os/dev_only/mean_reversion/study.json`.
No implementation, candidate simulation, or result exists at this commit.

The previous family failed its cash stability gate. This new hypothesis concerns
short-horizon reversal after a statistically excessive decline, subject to a
range filter and longer-regime downtrend veto. It is not a modification of the
previous trend/momentum candidate.

Eight chronological calendar folds cover 2019 through 2025 plus 2026-01-01 through
2026-08-19; earlier observations are warmup. All history is explicitly
development/retrospective. Rank by worst, median, then mean net fitness; mandatory
cash benchmark. BTC is a secondary comparison and cannot rescue failure vs cash.
Retain the prior score definition (CAGR minus twice absolute drawdown) without
loosening it after results. Annualized two-way turnover above 24x disqualifies.

Exactly 5 x (10 -> 6 + 4), seed 20260920, adjacent one-gene mutations, and the user's
eight small parameter domains. New SQLite persistence under a separate research
root. No IML. No access to Pi or production for this historical experiment.

Only HISTORICAL_REJECT or HISTORICAL_QUALIFIED_AWAITING_FORWARD may be reported.
On rejection, stop research immediately. On qualification, freeze the candidate
hash and prepare a read-only paper monitor for concrete review, stopping before
installation. Historical qualification never authorizes production trading.

FILES READ / SOURCE OF TRUTH: prior v2 results, AGENTS.md, SSOT README/master/chat
roles, relevant project/export/path contracts, current_issues, canonical registries
and registry workflow, previous evolution CONTRACT/README, Research OS v2 contract
and run-folder contract, Pi runtime runbook scope/canonical posture. SSOT sets
isolation; the user's explicit new-family request authorizes this dev-only scope.

Class D/B. Contract impact is a separate research family only. No old run,
production strategy/account contract, frontend, runtime or authority artifact is
changed. Validate JSON domains/budget and commit these documents before code.

Exact preregistration git add list:

```text
git add docs/mean-reversion-preregistration-20260920.md research_os/dev_only/mean_reversion/CONTRACT.md research_os/dev_only/mean_reversion/study.json source_of_truth/project_truth.json source_of_truth/paths_registry.json
```

Commit message: `Preregister separate BTC short-horizon mean-reversion family`.
Commit hash: the commit containing this document; recorded in the final audit.
