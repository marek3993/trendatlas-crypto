# VPS source-bundle manifest repair — 2026-10-19

Classification: B (release layout contract), C (pre-activation installation gate). No strategy-math or execution-policy change.

## FILES READ

AGENTS.md; source_of_truth/README.md; source_of_truth/master_state.md; source_of_truth/chat_roles.md; source_of_truth/project_truth.json; source_of_truth/export_contract.json; source_of_truth/paths_registry.json; source_of_truth/current_issues.md; canonical/script_registry.json; canonical/output_registry.json; canonical/registry_workflow.md; source_of_truth/pi_codex_runtime_workflow.md. Large registries were inspected for their Clean 50/50 entries.

Also: source_of_truth/clean_5050_multi_account.md; source_of_truth/clean_5050_contract.json; deploy/clean_5050/bootstrap_multi_account.py; scripts/production/build_clean_installer.py; tests/test_clean_5050_installer.py; web/tests/agent-authorization.test.ts; web/tests/production-boundary.test.ts; web/package.json; requirements-clean-execution.txt; docs/clean-5050-20261018/MULTI_ACCOUNT.md.

## SOURCE OF TRUTH

Parent commit: 1f46a94634f02344b5f926050597fd93583ff6a7. User-provided VPS result: INSTALL_FAILED_BEFORE_ACTIVATION, COMMAND_FAILED:/usr/bin/npm:1, 248/250 TS tests; Node v22.23.3 installed by operator. The existing Clean contract and user instruction preserve the two TS boundary tests and phase68g shutdown.

## Root cause and contract impact

The ZIP contained BUNDLE_MANIFEST.json, but bootstrap unpack() only wrote files listed inside that manifest. The manifest itself was omitted. Consequently, both unchanged TS boundary tests took their Git-checkout path in a Git-free release and failed. Earlier authoring validation used ZipFile.extractall(), which preserved the manifest and did not exercise this bootstrap defect.

The release-layout contract now explicitly requires preserving the original BUNDLE_MANIFEST.json bytes at the release root after all source entries pass hash validation. unpack() adds precisely that write. The existing SOURCE.json receipt remains separate. The new commit receives a new release path, so the failed 1f46a946 release need not be edited or deleted.

## Regression and validation

- Added test_unpack_preserves_bundle_manifest_at_release_root to the Python installer suite. It calls the real unpack() on a real builder bundle and checks root-file existence, byte identity and parsed manifest identity.
- Red/green check: the new test failed on the previous unpack() with the missing-root-manifest assertion, then passed after the one-line runtime fix.
- `python -m unittest discover -s tests -p test_clean_5050_installer.py -v`: 10 passed.
- `python scripts/production/build_clean_installer.py`: rebuilt the embedded installer and bundle_manifest.json, 142 source files.
- Loaded RUNTIME_SOURCE and BUNDLE_B64 from the generated installer, verified its bundle SHA and equality with the source bootstrap, then called the embedded unpack() in a fresh directory outside a Git repository. No generic ZIP extraction was used.
- From that extracted release, `python -m unittest discover -s tests -p 'test_clean_5050*.py' -v`: **92 passed**.
- From that extracted release's web directory, `npm test`: **250 passed / 18 files**, including the two previously failing unmodified boundary tests. Local runtime: Python 3.12.14, Node 24.19.0. Dependencies follow the existing lock/requirements; node_modules was linked from the existing local install.
- `git diff --check`: passed. The signal core, TS tests, execution policy and systemd service have no diff from the parent. No new historical replay, network exchange call or production activation was needed for this packaging-only fix.

Bundle SHA-256: 35140ce8070154611eeabf6958c5cf72ce2645b61629050d1e276e6cdec597df.

## Forbidden old path checked

Neither TS test was weakened or changed. The extracted release identifies itself using the manifest rather than requiring Git/data/outputs directories. No private key, generated data/outputs, unrelated untracked file or dependency directory is staged. No systemd unit, kill switch, VPS file or exchange state was changed in this session. Phase68g remains disabled according to the operator evidence.

## Exact files changed / git add list

- `deploy/clean_5050/bootstrap_multi_account.py`
- `deploy/clean_5050/bundle_manifest.json`
- `deploy/clean_5050/install_multi_account.py`
- `docs/clean-5050-20261018/INSTALLER_MANIFEST_FIX_20261019.md`
- `docs/clean-5050-20261018/MULTI_ACCOUNT.md`
- `source_of_truth/clean_5050_contract.json`
- `tests/test_clean_5050_installer.py`

```sh
git add -- deploy/clean_5050/bootstrap_multi_account.py deploy/clean_5050/bundle_manifest.json deploy/clean_5050/install_multi_account.py docs/clean-5050-20261018/INSTALLER_MANIFEST_FIX_20261019.md docs/clean-5050-20261018/MULTI_ACCOUNT.md source_of_truth/clean_5050_contract.json tests/test_clean_5050_installer.py
```

Commit message: `fix: preserve source bundle manifest during VPS extraction`

Commit hash: the containing commit is resolved in the PR #1 handoff and final response; an audit cannot embed its own Git commit hash.

## Operator handoff

The updated single PowerShell command in PR #1 uses the existing `$HOME\Downloads\ta-clean` checkout, `git fetch origin <full-sha>`, `git checkout --detach <full-sha>`, and Get-Content piped to SSH with ConnectTimeout=15. Each failed Git step stops before SSH. It does not use raw.githubusercontent.com. The command schedules installation and native VPS validation before explicit Clean activation; INSTALL_SCHEDULED_ON_VPS is not proof of activation. Final success remains CLEAN_MULTI_ACCOUNT_LIVE_AND_ALIGNED in /var/lib/trendatlas-clean-install/status.json. Native VPS result is pending the operator rerun.
