# Production executor in this repair branch

This main/audit-based repair imports the server executor, its dependencies and tests
from the deployed Pi commit `5ee031cef7de9c385056cec22f6511391d3e4f4f`.
It preserves exit-first reconciliation and per-account isolation. It does not import
the unrelated Next.js UI, authentication flows, database migrations or evolution work.
The deployed Pi keeps its existing complete web tree. The review overlays only these
explicit code files. `npm test` and `npm run typecheck` validate this server subset.

Production runs only as a child of `scripts/execution/run_trendatlas_production.py`.
Use the canonical service with `--no-submit` for review; no new automatic scheduler.
No-submit performs read-only account/metadata/authorization checks and never calls
exchange mutation or database status/journal mutation callbacks.
