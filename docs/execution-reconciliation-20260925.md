# Execution repair: 2026-09-25

Class C + B. The validated strategy selected AVAX 1.25x while the owner wallet remained BTC about 0.49x. Python policy, TypeScript asset unions and database checks disagreed with Production Core. Prior-day approval/authority artifacts, global account failure gates and deterministic retry loops independently prevented recovery.

The normative sources are `source_of_truth/production_execution_contract.json` and `source_of_truth/production_asset_universe_contract.json`. The former records the user-requested execution contract before implementation. The latter distinguishes current adapter capabilities from historical aggregate labels such as BASE; strategy selection mathematics is unchanged.

## Work ledger

| Task | Owner | Status | Next action | Blocker |
| --- | --- | --- | --- | --- |
| Python source contract and canonical reconciliation | python_audit | Implemented; regression tested | Final integration validation | None |
| Dynamic TypeScript execution, durable recovery and SQL migration | typescript_audit | Implemented; behavioral and database tests pass | Final integration validation | None |
| Account/model/outcome separation, health and deployment invariant | health_audit | Implemented; regression tested | Refresh current runtime for deployment verification | Stale local runtime is not deployment authority |
| Commit, Pi deployment, migration and canonical no-submit | root | In progress | Preserve runtime, deploy tested commit, verify no-submit | None |
| Financial live reconciliation | operator | Not performed by assistant | Operator-controlled live activation | Outside assistant action capability |

## Contract impact

- Asset and exposure come from the current validated Production Core. Exchange support comes from `metaAndAssetCtxs`.
- Only the explicit emergency `kill_switch` remains a common operator trade switch. Invocation controls no-submit. Per-user consent, signer authorization, provenance, locks and exchange constraints remain mandatory.
- Recover existing CLOIDs, reconcile journal-owned orders, reduce-only close all unwanted or short positions, verify each closure, then size the current target using fresh equity and entry margin.
- An unsupported/unaffordable new entry cannot veto a valid exit. Failed entry leaves confirmed CASH. Ambiguous submission stays unresolved until exchange evidence permits a residual plan.
- Durable signed expiry permits recovery of requests proven absent after expiry; historical requests without expiry evidence remain fail-closed. A retry never blindly repeats a CLOID.
- Temporary account failures remain eligible on later schedules and do not abort other accounts. Owner snapshot context is optional only in explicit multi-account mode, whose gateway reads every account fresh.
- Publication failure cannot erase completed execution evidence. Deterministic failures return exit 2, excluded from systemd restart; transient retries are bounded and the daily timer remains available.
- Wallet positions and performance never come from model fields. Public views separate the validated target, real wallet and last execution outcome.

## Verification coverage

Behavioral fixtures cover BTC approximately 0.49x to AVAX 1.25x, every derived supported target, cash, shorts, multiple positions, conflicting owned orders, margin/precision/unsupported entry, partial fills, power interruption, duplicate signals, prior-signal recovery, unavailable owner context, account isolation and no-submit with zero exchange writes. PGlite executes the real SQL migration, RLS, immutable journal triggers and lease functions. Next.js build, TypeScript typecheck, Python contract/orchestrator tests, compile checks and source scans are included.

Exact validation counts, file/add lists, commit IDs, Pi state and deployment evidence are recorded in the task's final receipt after deployment, rather than inventing a self-referential commit hash here.

Local validation before deployment: **262 Python tests and 26 subtests passed; 211 TypeScript tests passed across 15 suites (including four real PostgreSQL/PGlite migration tests); TypeScript typecheck, ESLint, Next.js production build, changed-Python compile checks, JSON parsing and `git diff --check` passed.** The active-source forbidden-token scan is clean. Generated data/outputs have no local diff.

## Deployment

1. Preserve Pi runtime, credentials, journals and existing overlays. Keep `/opt/market_regime_v1` as runtime root.
2. Stop the production service and install a persistent `--no-submit` service override before replacing execution code or applying its database schema.
3. Deploy the reviewed feature commit. The three existing Pi code overlays match the feature branch base byte-for-byte, so their content is retained in Git history.
4. Apply the additive execution migration; verify RLS and row counts. Install locked dependencies.
5. Use the canonical orchestrator under the same systemd environment in no-submit mode. Only the approved fast dependency chain is allowed.
6. Validate adapter-derived current assets with `npm run production:check-asset-support`, and dry-run `publish-existing` before any real publish.
7. Verify fresh target/account/plan, terminal no-submit report and timer enabled/active. Leave no-submit installed; no assistant exchange mutations are permitted.

Historical source mentions, historical migrations and non-trading path/request allowlists remain as history or technical safeguards; they are not active trading membership controls. The standalone canary/live-once/manual web submit paths are retired.
