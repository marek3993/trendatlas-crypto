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
