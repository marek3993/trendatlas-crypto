# Active Clean upgrade and diagnostics — 2026-10-19

Classification: **C** (execution, installer, scheduler), **B** (download/error contracts), **A** (drawdown wording). No class D strategy change.

## FILES READ / SOURCE OF TRUTH

Read the repository truth order: source_of_truth/{README.md,master_state.md,chat_roles.md,project_truth.json,export_contract.json,paths_registry.json,current_issues.md}, canonical/{script_registry.json,output_registry.json,registry_workflow.md}, and source_of_truth/pi_codex_runtime_workflow.md. The user's current Clean multi-account instructions and source_of_truth/clean_5050_contract.json govern this continuation; old phase68g/key instructions are not deployment authority.

Implementation reads: bootstrap_multi_account.py, build_clean_installer.py, both Clean systemd units, run_clean_multi_account.py, fetch_data.py, portfolio-engine.ts, repository.ts, hyperliquid-live-gateway.ts, hyperliquid-l1-signing.ts, run-clean-multi-account.ts, clean-public.ts, clean-performance.tsx, clean5050-copy.json, app.py, their existing installer/portfolio/gateway tests, and the prior MULTI_ACCOUNT/INSTALLER_MANIFEST_FIX audits.

## Root causes and verified limits

- The portfolio catch discarded the original error and returned one generic sentence. If finishRun also failed it discarded even that sentence. Repository wrappers discarded the underlying SQL error. updateLeverage discarded exchange rejection text.
- The installer created the Clean user without the supplementary production group needed to traverse the existing 0750 legacy guard path. Both its transient preflight and production unit need that access.
- The public HTTP response limit was 16 MiB, below the operator-observed 17.8 MB exchangeInfo response. Incorporates the equivalent of Marek's local-only 00109d0 change; that local commit is not a remote ancestor.
- The existing installer deliberately refused an active timer and enabled it before the first manual run. Upgrades now require --upgrade-active, quiesce the scheduler, hold the same production.lock as the canonical worker, and refuse to interrupt in-flight work.
- Read-only Supabase evidence: one Clean run for closed day 2026-10-18, weights BTC .5 / NEAR .5, FAILED with the old generic error, portfolio_completed_at null; its actions query returned zero rows. The run schema and nonce/lease RPC definitions exist. This does **not** identify the original failing operation or certify that an updateLeverage request was never sent. No DB mutations, signing material retrieval or exchange writes were performed in this session.
- No operator SSH key or SSH agent is available here. The real VPS run and FILLED_AND_ALIGNED remain unverified until the operator runs the pinned command.

## Contract impact and upgrade sequence

The source contract was changed and validated before implementation. Diagnostics contain stage + error name/message (+ one cause/code), redact known secrets, 0x values, long hex/base64 tokens, URLs and control characters **before** the 200-character bound. Only that string is sent to receipt reason, DB sanitized_error and structured stderr (systemd journal); no raw exception, stack, request or signed payload is logged. Receipt output survives DB finalization failure. Unknown submission classification and existing CLOID recovery are preserved.

The HTTP response cap is 64 MiB; the separate archive-entry bound is unchanged. Existing policy settings and journals persist. Before replacement the timer is disabled, a running/activating worker is rejected, and production.lock is held across staging, validation and read-only preflight. The policy is disarmed during replacement. A root-private before-SHA-PID.json saves the prior policy/current release pointer. Usermod appends trendatlas-production; the group is also explicit in both systemd execution contexts. The credential file remains the existing EnvironmentFile, parsed by systemd.

Only after native tests, reference validation and read-only preflight does the current symlink switch. With --activate-live, the installer releases the lock and calls systemctl start trendatlas-clean-production.service **once**. Even exit 2 reads and prints a fresh sanitized receipt if present. An old receipt or wrong signal/day cannot pass activation. A complete fresh result must have all_accounts_aligned=true and one NO_ACTION or FILLED_AND_ALIGNED result for each preflight account. NO_ACTION is reported as such, never relabelled as a new fill. Failure after replacement leaves Clean disarmed and its timer disabled; no automatic rollback/resubmission or legacy restart occurs.

After verified success, only the systemd timer timestamp is reset/touched to account for the completed manual cycle, then the 00:10 UTC Persistent timer resumes. This avoids immediately replaying a missed timer tick. Deleting the timestamp alone is insufficient for an already-loaded timer: timer_start reads an existing mtime into last_trigger, while timer_clean only unlinks it. References: [systemd.timer](https://www.freedesktop.org/software/systemd/man/257/systemd.timer.html), [timer.c timer_setup_persistent/timer_start/timer_clean](https://github.com/systemd/systemd/blob/main/src/core/timer.c).

## Public page verification

Read the actual public Storage version **c321e3ea9c9bd1459b89d17f210270c8378efdd1ecb6c585fc281c519cc7b9af** from project figgfdxmlaawoqsgidyx, bucket trendatlas-clean-public. Window: 2021-01-01 through 2026-10-18, 2,117 days, all-universe 694 symbols. Artifact values: CAGR 86.50984877739702%, MaxDD -51.92849394257452%, Sharpe 1.3531462955351043. Independently recomputed drawdown from the public CSV: the same value, peak 2021-02-19, trough 2021-08-17. These are historical model results with the artifact's disclosed cost/funding/cash assumptions, not live PnL; 41 funding proxy days are recorded.

The shared SK/EN wording now says drawdowns around 50%. No metric value is hardcoded. Built Next.js was served locally with these downloaded, checksum-validated artifacts: both languages returned HTTP 200 and rendered 86.5 / -51.9 / 1.35 (localized), the new wording and Clean/BTC chart. The observed public URL https://trendatlas-accounts.vercel.app redirected to /login; the Vercel connector returned no teams. Therefore the external frontend's deployment/display is **not confirmed**. The VPS installer publishes data; it does not deploy Vercel. Both Next.js and Streamlit consume the same wording file.

## Regression tests and validation

- 99 Python Clean tests passed, including 18 MiB acceptance / over-64 MiB rejection; active upgrade opt-in; busy worker/lock refusal; policy preservation; lock held through preflight/released before service; group access; one manual start; timer timestamp after receipt; failure/stale receipt leaving timer disabled.
- 260 TypeScript tests passed, including failures at readActions, readUnresolvedActions, reserveNonce, prepareOrder, setLeverageOne; bounded redaction; error code retention; DB-journal failure fallback; sanitized exchange rejection; existing ambiguous-submission recovery.
- npm run typecheck and npm run build passed. The generated installer's actual embedded unpack() was used to create a Git-free release. That release passed all 99 Python / 260 TS tests and typecheck, with BUNDLE_MANIFEST.json at its root.
- Installer build: python scripts/production/build_clean_installer.py. Deterministic source bundle: 145 files; SHA256 **0a3bc3f6c47af2d4a8a7e5bdf673aafc65c82c1c50835318323c21a9bc7867ce**. No runtime data or keys bundled.
- Commands: PYTHONPATH=src <validated-python> -m unittest discover -s tests -p 'test_clean_5050*.py' -v; cd web && npm test; npm run typecheck; npm run build; git diff --check.
- Forbidden paths checked: core.py unchanged; data/ and outputs/ tracked files unchanged; the two original generated-data boundary tests unchanged; no single-key deployment or old service start; no authority snapshot modifications. The pre-existing untracked temporary output and local venv remain unstaged.
- The full historical replay was not rerun here for a packaging/diagnostic change. The operator's prior 18-point reference pass is evidence from the user; this installer still requires it again on VPS. No full-refresh was run in this authoring session.

## Exact files changed / git add list

```text
deploy/clean_5050/bootstrap_multi_account.py
deploy/clean_5050/bundle_manifest.json
deploy/clean_5050/install_multi_account.py
deploy/systemd/trendatlas-clean-production.service
docs/clean-5050-20261018/ACTIVE_UPGRADE_20261019.md
source_of_truth/clean_5050_contract.json
src/trendatlas_clean/fetch_data.py
tests/test_clean_5050_fetch_bound.py
tests/test_clean_5050_installer.py
web/scripts/run-clean-multi-account.ts
web/src/content/clean5050-copy.json
web/src/server/multi-account-executor/hyperliquid-live-gateway.ts
web/src/server/multi-account-executor/portfolio-engine.ts
web/src/server/multi-account-executor/repository.ts
web/src/server/multi-account-executor/safe-error.ts
web/tests/clean-market-data.test.ts
web/tests/clean-portfolio.test.ts
web/tests/clean-safe-error.test.ts
```

Commit message: `fix(clean): preserve live errors and safely upgrade active multi-account runtime`

Commit hash: recorded in PR #1 and the operator response after committing; the Git hash cannot be embedded into its own commit. Parent: `1df6dd340d16ea1fd2a12d81222829c2870fd7e0`.
