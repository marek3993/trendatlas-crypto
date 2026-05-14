# MRV1 Nightly Runtime Deployment

This deployment is intentionally limited to the safe public status publishing chain:

- default producer mode is `publish-existing`
- nightly service refreshes fast dependencies before `publish-existing`
- long refresh requires explicit `--mode full-refresh`
- no real orders
- no execution submit path
- no `source_of_truth` writes from the runtime loop
- no strategy semantics changes
- execution outputs remain operational artifacts, not official truth

The nightly service performs exactly one controlled pass in this order:

1. `scripts/execution/run_pi_fast_daily_authority_refresh.py`
2. fast Phase60 dependency: `--dependency-only --model-key phase60_restore_trx_sol_base`
3. fast Phase63 dependency: `--winner-only --variant-key phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3`
4. `scripts/execution/run_pi_authoritative_producer.py --mode publish-existing --dry-run`
5. `scripts/execution/run_pi_authoritative_producer.py --mode publish-existing` only after dry-run success and only when `MRV1_ENABLE_AUTHORITY_PUBLISH=1` and `MRV1_AUTHORITY_MODE=authoritative`

`journald` captures the pass through `mrv1-nightly-runtime.service`. Pi installs that use `mrv1-daily-live.service` must use the same wrapper.

## Preconditions

- Linux machine with `systemd`
- repo deployed at `/opt/market_regime_v1`
- writable repo ownership for user `mrv1`
- `execution/config/execution_mode.json` forced to a safe runtime profile before enabling the timer
- `execution/config/hyperliquid_account.json` present with the real Hyperliquid account address

## Exact install commands

Run from the repo root on the deployment machine:

```bash
sudo useradd --system --create-home --home-dir /home/mrv1 --shell /usr/sbin/nologin mrv1 || true
sudo mkdir -p /opt/market_regime_v1
sudo rsync -a --delete ./ /opt/market_regime_v1/
sudo chown -R mrv1:mrv1 /opt/market_regime_v1
sudo -u mrv1 python3 -m venv /opt/market_regime_v1/.venv
sudo -u mrv1 /opt/market_regime_v1/.venv/bin/pip install --upgrade pip
sudo -u mrv1 /opt/market_regime_v1/.venv/bin/pip install -r /opt/market_regime_v1/requirements.txt requests
sudo tee /opt/market_regime_v1/execution/config/execution_mode.json >/dev/null <<'EOF'
{
  "mode": "read_only",
  "trading_enabled": false,
  "dry_run_enabled": true,
  "kill_switch": true,
  "write_app_status": true,
  "write_raw_snapshot": true,
  "fail_fast": true
}
EOF
sudo install -D -m 0644 /opt/market_regime_v1/deploy/systemd/mrv1-nightly-runtime.service /etc/systemd/system/mrv1-nightly-runtime.service
sudo install -D -m 0644 /opt/market_regime_v1/deploy/systemd/mrv1-daily-live.service /etc/systemd/system/mrv1-daily-live.service
sudo install -D -m 0644 /opt/market_regime_v1/deploy/systemd/mrv1-nightly-runtime.timer /etc/systemd/system/mrv1-nightly-runtime.timer
sudo systemctl daemon-reload
sudo systemctl enable --now mrv1-nightly-runtime.timer
```

If `/opt/market_regime_v1/execution/config/hyperliquid_account.json` does not exist yet:

```bash
sudo cp /opt/market_regime_v1/execution/config/hyperliquid_account.json.template /opt/market_regime_v1/execution/config/hyperliquid_account.json
sudo chown mrv1:mrv1 /opt/market_regime_v1/execution/config/hyperliquid_account.json
```

## Exact validation commands

Verify the unit files:

```bash
sudo systemd-analyze verify /etc/systemd/system/mrv1-nightly-runtime.service /etc/systemd/system/mrv1-daily-live.service /etc/systemd/system/mrv1-nightly-runtime.timer
```

Run one pass immediately:

```bash
sudo systemctl start mrv1-nightly-runtime.service
```

Check service and timer state:

```bash
sudo systemctl status mrv1-nightly-runtime.service --no-pager
sudo systemctl status mrv1-nightly-runtime.timer --no-pager
sudo systemctl list-timers mrv1-nightly-runtime.timer --all
```

Check journald logs:

```bash
sudo journalctl -u mrv1-nightly-runtime.service -n 200 --no-pager
sudo journalctl -u mrv1-nightly-runtime.service --since "today 00:00" --no-pager
```

Check the expected operational artifacts:

```bash
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/refresh_pipeline/materialize_execution_app_exports_report.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/app_snapshot/app_product_snapshot.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/app_snapshot/app_runtime_snapshot.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/authority/latest_attempt_status.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/authority/latest_successful_snapshot.json
sudo -u mrv1 cat /opt/market_regime_v1/outputs/execution/authority/latest_attempt_status.json
```

Check that `source_of_truth` stayed untouched:

```bash
sudo -u mrv1 git -C /opt/market_regime_v1 status --short -- source_of_truth
```

## Operational notes

- The timer runs daily at `00:10:00 UTC`, which keeps a simple post-close buffer for 1D candles.
- `Persistent=true` means a missed nightly run is triggered once after the machine comes back up.
- `Restart=no` keeps each timer activation to one controlled pass only; if a pass fails, inspect the journal, fix the cause, and rerun manually.
- `ProtectSystem=strict` plus `ReadWritePaths=/opt/market_regime_v1/data /opt/market_regime_v1/outputs /opt/market_regime_v1__authority_publish` means runtime writes are confined to operational artifacts, refreshed market data, and the dedicated authority publish clone.
- `ReadOnlyPaths=/opt/market_regime_v1/source_of_truth` adds an explicit runtime guardrail against truth writes from the service.
- `ExecStartPost=/usr/bin/test -f ...` checks make the unit fail if the expected execution artifacts were not produced.
- The service never calls a live-order script. It refreshes fast dependency inputs, verifies app freshness, runs publish-existing dry-run first, and runs the real publish only through the env-gated authority producer path.

## Manual Pi authority publish

This is the first real producer-side publish path only:

- no `app.py` change
- no app consumer cutover
- no UI change
- Pi stays the only automatic production producer
- PC stays non-authoritative
- GitHub Actions stays non-authoritative

Exact first-run manual command on the Pi:

```bash
cd /opt/market_regime_v1
export MRV1_AUTHORITY_REPO_REMOTE=origin
export MRV1_AUTHORITY_REPO_BRANCH=main
export MRV1_AUTHORITY_PUBLISH_TREE=/opt/market_regime_v1__authority_publish
export MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS=3
export MRV1_AUTHORITY_GIT_USER_NAME="MRV1 Pi Authority Publisher"
export MRV1_AUTHORITY_GIT_USER_EMAIL="mrv1-pi-authority@example.com"
.venv/bin/python scripts/execution/run_pi_fast_daily_authority_refresh.py
```

Files that must exist after a successful run:

```bash
/opt/market_regime_v1/outputs/execution/authority/latest_attempt_status.json
/opt/market_regime_v1/outputs/execution/authority/latest_successful_snapshot.json
```

Exact clean publish clone flow:

1. Resolve the runtime checkout remote URL from `/opt/market_regime_v1`.
2. Clone or reuse `/opt/market_regime_v1__authority_publish` as a separate clean git checkout.
3. Fetch `origin/main`, check out `main`, hard-reset to `origin/main`, and clean untracked files in the publish clone.
4. Copy only `outputs/execution/authority/latest_attempt_status.json` and `outputs/execution/authority/latest_successful_snapshot.json` into the publish clone.
5. Commit only those pathspecs and push only from the publish clone.
6. If push is rejected by remote drift, repeat from a fresh fetch/reset/clean cycle.

Exact validation commands:

```bash
cd /opt/market_regime_v1
export MRV1_AUTHORITY_REPO_REMOTE=origin
export MRV1_AUTHORITY_REPO_BRANCH=main
export MRV1_AUTHORITY_PUBLISH_TREE=/opt/market_regime_v1__authority_publish
export MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS=3
export MRV1_AUTHORITY_GIT_USER_NAME="MRV1 Pi Authority Publisher"
export MRV1_AUTHORITY_GIT_USER_EMAIL="mrv1-pi-authority@example.com"
.venv/bin/python scripts/execution/run_pi_fast_daily_authority_refresh.py
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" status --short
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" show --pretty= --name-only HEAD
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" show HEAD:outputs/execution/authority/latest_attempt_status.json
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" show HEAD:outputs/execution/authority/latest_successful_snapshot.json
git -C /opt/market_regime_v1 status --short
```

Exact rollback:

```bash
cd /opt/market_regime_v1
export MRV1_AUTHORITY_REPO_REMOTE=origin
export MRV1_AUTHORITY_REPO_BRANCH=main
export MRV1_AUTHORITY_PUBLISH_TREE=/opt/market_regime_v1__authority_publish
export MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS=3
export MRV1_AUTHORITY_GIT_USER_NAME="MRV1 Pi Authority Publisher"
export MRV1_AUTHORITY_GIT_USER_EMAIL="mrv1-pi-authority@example.com"
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" fetch "$MRV1_AUTHORITY_REPO_REMOTE" "$MRV1_AUTHORITY_REPO_BRANCH"
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" checkout -B "$MRV1_AUTHORITY_REPO_BRANCH" "$MRV1_AUTHORITY_REPO_REMOTE/$MRV1_AUTHORITY_REPO_BRANCH"
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" revert --no-edit HEAD
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" push "$MRV1_AUTHORITY_REPO_REMOTE" "HEAD:$MRV1_AUTHORITY_REPO_BRANCH"
```
