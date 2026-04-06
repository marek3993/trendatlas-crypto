# MRV1 Nightly Runtime Deployment

This deployment is intentionally limited to the existing safe execution chain:

- `read_only` only
- `dry_run` only
- no real orders
- no `source_of_truth` writes from the runtime loop
- no strategy semantics changes
- execution outputs remain operational artifacts, not official truth

The nightly service performs exactly one controlled pass in this order:

1. `scripts/daily_refresh_app_pipeline.py`
2. `scripts/execution/materialize_execution_app_exports.py`
3. `scripts/execution/hyperliquid_read_only_snapshot.py`
4. `scripts/execution/build_execution_intent_from_strategy_exports.py`
5. `scripts/execution/run_dry_execution_bridge.py`
6. `scripts/execution/render_execution_app_status.py`

`journald` captures the pass through `mrv1-nightly-runtime.service`.

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
sudo systemd-analyze verify /etc/systemd/system/mrv1-nightly-runtime.service /etc/systemd/system/mrv1-nightly-runtime.timer
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
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/read_only/hyperliquid_account_snapshot.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/intents/latest_execution_intent.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/dry_run/latest_dry_run_decision.json
sudo -u mrv1 test -f /opt/market_regime_v1/outputs/execution/live_status/execution_status.json
sudo -u mrv1 cat /opt/market_regime_v1/outputs/execution/dry_run/latest_dry_run_decision.json
```

Check that `source_of_truth` stayed untouched:

```bash
sudo -u mrv1 git -C /opt/market_regime_v1 status --short -- source_of_truth
```

## Operational notes

- The timer runs daily at `00:10:00 UTC`, which keeps a simple post-close buffer for 1D candles.
- `Persistent=true` means a missed nightly run is triggered once after the machine comes back up.
- `Restart=no` keeps each timer activation to one controlled pass only; if a pass fails, inspect the journal, fix the cause, and rerun manually.
- `ProtectSystem=strict` plus `ReadWritePaths=/opt/market_regime_v1/data /opt/market_regime_v1/outputs` means runtime writes are confined to operational artifacts and refreshed market data.
- `ReadOnlyPaths=/opt/market_regime_v1/source_of_truth` adds an explicit runtime guardrail against truth writes from the service.
- `ExecStartPost=/usr/bin/test -f ...` checks make the unit fail if the expected execution artifacts were not produced.
- Because `render_execution_app_status.py` runs last in this deployment, the final `outputs/execution/live_status/execution_status.json` reflects the snapshot renderer output; the dry-run decision remains in `outputs/execution/dry_run/latest_dry_run_decision.json`.
- The service never calls a live-order script. It only refreshes data, rematerializes exports, fetches a read-only snapshot, builds intent, produces a dry-run decision, and refreshes app status.
