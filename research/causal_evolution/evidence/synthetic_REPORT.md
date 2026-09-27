# Frozen causal evolution result

Decision: **REJECT**. Previously studied history is not new sealed evidence.

|Island|Arm|Seed|Slot|CAGR|MDD|Sharpe|Calmar|BTC CAGR|Result|
|---|---|---:|---|---:|---:|---:|---:|---:|---|
|F_spot|deepseek|1701|A|114.63%|21.71%|3.79|5.28|38.96%|REJECT|
|F_spot|deepseek|1701|B|114.63%|21.71%|3.79|5.28|38.96%|REJECT|
|F_spot|deepseek|1701|C|114.63%|21.71%|3.79|5.28|38.96%|REJECT|
|F_spot|deterministic|1701|A|114.63%|21.71%|3.79|5.28|38.96%|REJECT|
|F_spot|deterministic|1701|B|114.63%|21.71%|3.79|5.28|38.96%|REJECT|
|F_spot|deterministic|1701|C|114.63%|21.71%|3.79|5.28|38.96%|REJECT|
|F_spot|deepseek|2903|A|113.95%|21.94%|3.77|5.19|38.96%|REJECT|
|F_spot|deepseek|2903|B|12.01%|17.54%|1.22|0.68|38.96%|REJECT|
|F_spot|deepseek|2903|C|113.95%|21.94%|3.77|5.19|38.96%|REJECT|
|F_spot|deterministic|2903|A|113.95%|21.94%|3.77|5.19|38.96%|REJECT|
|F_spot|deterministic|2903|B|12.01%|17.54%|1.22|0.68|38.96%|REJECT|
|F_spot|deterministic|2903|C|113.95%|21.94%|3.77|5.19|38.96%|REJECT|
|F_spot|deepseek|4517|A|88.28%|19.59%|3.36|4.51|38.96%|REJECT|
|F_spot|deepseek|4517|B|88.28%|19.59%|3.36|4.51|38.96%|REJECT|
|F_spot|deepseek|4517|C|88.28%|19.59%|3.36|4.51|38.96%|REJECT|
|F_spot|deterministic|4517|A|88.28%|19.59%|3.36|4.51|38.96%|REJECT|
|F_spot|deterministic|4517|B|88.28%|19.59%|3.36|4.51|38.96%|REJECT|
|F_spot|deterministic|4517|C|88.28%|19.59%|3.36|4.51|38.96%|REJECT|

Complete metrics/costs/turnover/concentration/stresses: `all_results.csv`. Per-year, venue, capital and stress: `annual_folds_stresses_capacity.csv`. All development attempts: SQLite + `development_folds.csv`.

DeepSeek API calls: 0; tokens: 0; cost upper estimate USD 0.000000.

No strategy is deployed. Prospective start 2026-09-27; next scheduled refit 2027-01-01, conditional on 30 new closed UTC days and complete append-only data.

A/B/C decision objects:
```json
{
  "A": null,
  "B": null,
  "C": null,
  "D": "REJECT",
  "E": "FROZEN_FORWARD_CANDIDATES_AWAIT_CLOSED_PROSPECTIVE_DATA",
  "history": "PREVIOUSLY_SEEN_NOT_GLOBAL_SEALED"
}
```
