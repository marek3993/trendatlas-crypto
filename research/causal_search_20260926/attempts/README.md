# Execution attempts

The first serial startup verified inputs and completed at least the first 27
variants (each with normal, double-cost and delayed replay) in 62.1 seconds.
It was interrupted before a partition completed, before candidate selection,
and before any market metric was printed or inspected. No search choices or
parameters changed. The implementation was changed only to execute the six
independent pre-registered partition budgets in six worker processes.

`serial_startup_freeze.json` preserves the original implementation fingerprint.
These repeated computations are not additional parameter trials; the search
still has 1,944 unique mode/parameter combinations. No partial-result cache was
accepted from the different implementation fingerprint.

The second startup was interrupted during the grid, before complete partition
results or OOS selection, after review found that the delay stress lagged the
whole decision stream. The source contract requires an additional entry delay,
with timely exits. The corrected engine queues the frozen entry asset/exposure/
ATR source for the next bar; a superseded target expires, and ordinary exits and
protection continue using their normal availability. Regression tests cover
entry timestamps, frozen source/exposure, timely CASH exits and expired signals.
No universe, risk parameter, fold, cost or search budget changed. The previous
fingerprint is retained in `entry_delay_correction_freeze.json`; its results are
not used. The final search uses a new empty cache and is run in full.

The third run completed all 1,944 grid candidates and their two stress scenarios,
but its in-memory NumPy Calmar scalar was rejected by the objectives evaluator's
strict JSON-native type validation. This made every policy choose CASH. Loading
the same metrics from JSON accepted the values and exposed the discrepancy.
These zero-activity OOS reports are invalid and are not research findings.
`native_scalar_rejection_freeze.json` and `native_scalar_rejection_manifest.json`
preserve that run's identity; its complete files remain in local scratch.
The runner now reads freshly written cache records through the same JSON boundary
as a cached run, without weakening finite-value validation. A regression requires
both paths to choose the same non-CASH candidate. The engine also explicitly
returns Calmar as a native float, with all summary scalars covered by a type
regression. A new empty-cache full search repeats the unchanged mathematical
rules, universe, variants, folds, costs and selection rule.
Only development/validation metrics were inspected to diagnose the interface
failure; no market OOS candidate outcome informed this correction.
