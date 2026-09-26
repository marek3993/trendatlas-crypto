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
