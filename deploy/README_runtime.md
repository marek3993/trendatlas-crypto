# TrendAtlas Single Production Orchestrator Deployment

The only automatic production entrypoint is:

- `scripts/execution/run_trendatlas_production.py`

It owns the complete locked daily state machine:

- refresh and health validation
- Production Core, canonical intent, and canonical gate
- fresh real account reconciliation with equity-based target sizing
- optional controlled live execution with durable pre-submit journal and deterministic CLOID
- post-trade account verification, dashboard materialization, and final authority publish

Operational constraints:

- long refresh requires explicit `--mode full-refresh`
- `--no-submit` validates the encrypted signer credential and exchange-side named-agent authorization but never loads the order-submission adapter
- default execution submits only when every current-run invariant passes
- no `source_of_truth` writes from the runtime loop
- authority success is not published until required execution and verification finish
- execution artifacts remain operational evidence, not Production Core or account truth

## Preconditions

- Linux machine with `systemd`
- repo deployed at `/opt/market_regime_v1`
- runtime user `trendatlas`
- live activation configuration reviewed explicitly before enabling the timer
- `execution/config/hyperliquid_account.json` present with the real Hyperliquid account address
- systemd 257+ with `systemd-creds`; this Pi uses `LoadCredentialEncrypted` with the host key because no usable TPM2 device is present

## Exact install commands

Run from the repo root on the deployment machine:

```bash
sudo install -D -m 0644 /opt/market_regime_v1/deploy/systemd/mrv1-production.service /etc/systemd/system/mrv1-production.service
sudo install -D -m 0644 /opt/market_regime_v1/deploy/systemd/mrv1-production.timer /etc/systemd/system/mrv1-production.timer
sudo systemctl daemon-reload
sudo systemctl disable mrv1-production.timer
```

This stages the target units without creating a competing scheduler. Keep the existing
`mrv1-daily-live.timer` active until the credential is provisioned and the full
`--no-submit` preflight passes.

If `/opt/market_regime_v1/execution/config/hyperliquid_account.json` does not exist yet:

```bash
sudo cp /opt/market_regime_v1/execution/config/hyperliquid_account.json.template /opt/market_regime_v1/execution/config/hyperliquid_account.json
sudo chown trendatlas:trendatlas /opt/market_regime_v1/execution/config/hyperliquid_account.json
```

## One-time encrypted credential provisioning

Do not pass the private key as an argument, environment variable, redirected file, or
chat message. Run the provisioner from a local interactive Pi terminal; it prompts once
with hidden input and sends the value only over stdin to `systemd-creds`:

```bash
sudo /opt/market_regime_v1/.venv/bin/python /opt/market_regime_v1/scripts/execution/provision_hyperliquid_systemd_credential.py
```

The encrypted blob is written as root-owned mode `0400` at
`/etc/credstore.encrypted/mrv1-production.hyperliquid-agent-private-key`. The unit maps
it to the private per-service credential named `hyperliquid-agent-private-key`.

## Exact validation commands

Verify the unit files:

```bash
sudo systemd-analyze verify /etc/systemd/system/mrv1-production.service /etc/systemd/system/mrv1-production.timer
```

Run a safe no-submit preflight inside a transient systemd unit so the decrypted value is
available only through a private service credential mount:

```bash
sudo systemd-run --unit=mrv1-production-preflight --wait --collect --pipe --property=Type=oneshot --property=User=trendatlas --property=Group=trendatlas --property=WorkingDirectory=/opt/market_regime_v1 --property=Environment=MRV1_HYPERLIQUID_CREDENTIAL_NAME=hyperliquid-agent-private-key --property=Environment=MRV1_HYPERLIQUID_ACCOUNT_ADDRESS=0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856 --property=Environment=MRV1_HYPERLIQUID_AGENT_NAME=TrendAtlasProd --property=LoadCredentialEncrypted=hyperliquid-agent-private-key:/etc/credstore.encrypted/mrv1-production.hyperliquid-agent-private-key /opt/market_regime_v1/.venv/bin/python /opt/market_regime_v1/scripts/execution/run_trendatlas_production.py --no-submit
```

Only after that preflight reports `PREFLIGHT_READY`, `live_order_chain=NOT_INVOKED`,
`real_order_sent=false`, and signer validation `PASS`, migrate the recurring scheduler:

```bash
sudo systemctl disable --now mrv1-daily-live.timer mrv1-nightly-runtime.timer mrv1-runtime.timer mrv1-daily-preview.timer
sudo systemctl enable --now mrv1-production.timer
```

Check service and timer state:

```bash
sudo systemctl status mrv1-production.service --no-pager
sudo systemctl status mrv1-production.timer --no-pager
sudo systemctl list-timers mrv1-production.timer --all
```

Check journald logs:

```bash
sudo journalctl -u mrv1-production.service -n 200 --no-pager
sudo journalctl -u mrv1-production.service --since "today 00:00" --no-pager
```

## Multi-account execution cutover

The approved cutover keeps `mrv1-production.timer` and `run_trendatlas_production.py` as the only scheduler and entrypoint. It replaces only the execution backend.

Before installing the updated unit, create the root-owned environment file from the tracked placeholder without printing its values:

```bash
sudo install -o root -g trendatlas -m 0640 deploy/systemd/trendatlas-multi-account.env.example /etc/default/trendatlas-multi-account
sudoedit /etc/default/trendatlas-multi-account
```

Install dependencies and validate without an exchange write:

```bash
cd /opt/market_regime_v1/web
sudo -u trendatlas env PATH=/usr/bin:/bin /usr/bin/npm ci
cd /opt/market_regime_v1
sudo install -D -m 0644 deploy/systemd/mrv1-production.service /etc/systemd/system/mrv1-production.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/mrv1-production.service /etc/systemd/system/mrv1-production.timer
sudo systemctl disable --now mrv1-production.timer
sudo systemd-run --unit=mrv1-multi-account-preflight --wait --collect --pipe --property=Type=oneshot --property=User=trendatlas --property=Group=trendatlas --property=WorkingDirectory=/opt/market_regime_v1 --property=EnvironmentFile=/etc/default/trendatlas-multi-account --property=Environment=MRV1_EXECUTION_BACKEND=multi_account --property=Environment=MRV1_MULTI_ACCOUNT_WEB_ROOT=/opt/market_regime_v1/web --property=Environment=MRV1_MULTI_ACCOUNT_NODE_BINARY=/usr/bin/node --property=Environment=MRV1_HYPERLIQUID_ACCOUNT_ADDRESS=0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856 /opt/market_regime_v1/.venv/bin/python /opt/market_regime_v1/scripts/execution/run_trendatlas_production.py --no-submit
```

Do not start or enable the production timer until the preflight result, exact eligible account set, and rollback readiness have been reviewed. The Vercel environment remains in `disabled` execution mode.

Check the expected operational artifacts:

```bash
sudo -u trendatlas test -f /opt/market_regime_v1/outputs/execution/refresh_pipeline/materialize_execution_app_exports_report.json
sudo -u trendatlas test -f /opt/market_regime_v1/outputs/execution/app_snapshot/app_product_snapshot.json
sudo -u trendatlas test -f /opt/market_regime_v1/outputs/execution/app_snapshot/app_runtime_snapshot.json
sudo -u trendatlas test -f /opt/market_regime_v1/outputs/execution/authority/latest_attempt_status.json
sudo -u trendatlas test -f /opt/market_regime_v1/outputs/execution/authority/latest_successful_snapshot.json
sudo -u trendatlas test -f /opt/market_regime_v1/outputs/execution/production_runs/latest_production_run.json
```

Check that `source_of_truth` stayed untouched:

```bash
sudo -u trendatlas git -C /opt/market_regime_v1 status --short -- source_of_truth
```

## Operational notes

- The timer runs daily at `00:10:00 UTC`, which keeps a simple post-close buffer for 1D candles.
- `Persistent=true` means a missed nightly run is triggered once after the machine comes back up.
- `Restart=on-failure` with `RestartSec=15min` retries the same canonical service after a temporary network/API or other fail-closed error. A successful pass is not restarted; the orchestrator lock, fresh-data gates, deterministic CLOID, durable journal recovery, and account read-back remain authoritative on every retry.
- `ProtectSystem=strict` plus `ReadWritePaths=/opt/market_regime_v1/data /opt/market_regime_v1/outputs /opt/market_regime_v1__authority_publish` means runtime writes are confined to operational artifacts, refreshed market data, and the dedicated authority publish clone.
- `ReadOnlyPaths=/opt/market_regime_v1/source_of_truth` adds an explicit runtime guardrail against truth writes from the service.
- `ExecStartPost=/usr/bin/test -f ...` checks make the unit fail if the expected execution artifacts were not produced.
- The service has one entrypoint. Focused refresh, publish, gate, and submit scripts remain internal and must not have enabled competing timers.

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
