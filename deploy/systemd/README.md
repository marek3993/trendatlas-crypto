# Research OS Pi Bring-Up

This is the exact bring-up path for the dev-only, non-authoritative Raspberry Pi orchestrator deployment, with the desktop PC kept as the heavy-validation worker.

Guardrails remain unchanged:

- `dev_only=true`
- `non_authoritative=true`
- `fail_closed=true`
- no `source_of_truth` mutation
- no canonical truth mutation
- no live trading logic
- no strategy logic changes

## Pi prerequisites

Use a Pi that can run the repo at `/opt/market_regime_v1` with:

- `git`
- `python3`
- `python3-venv`
- `python3-dev`
- `build-essential`
- `libffi-dev`
- `libssl-dev`
- `redis-server`

Install them with:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-dev build-essential libffi-dev libssl-dev redis-server
```

## Exact Pi path expectation

The Pi units are pinned to this repo root:

```bash
/opt/market_regime_v1
```

Copy the full repo there, not a partial subtree. The orchestrator reads:

- `configs/runtime/runtime_config.pi_orchestrator.template.json`
- `configs/families/family_registry.template.json`
- `outputs/research_os/dev_only/non_authoritative_*`
- `outputs/research_os/dev_only/mvp/*`

## Exact env file

Create this file on the Pi:

```bash
sudo install -d /etc/default
sudo tee /etc/default/research_os >/dev/null <<'EOF'
OPENAI_API_KEY=replace_with_real_key
REDIS_URL=redis://127.0.0.1:6379/0
RESEARCH_OS_ROOT=/opt/market_regime_v1
EOF
```

These three variables are required for bring-up:

- `OPENAI_API_KEY`
- `REDIS_URL`
- `RESEARCH_OS_ROOT`

## Redis bring-up on Pi

```bash
sudo systemctl enable --now redis-server
redis-cli -u redis://127.0.0.1:6379/0 ping
```

Expected result:

```bash
PONG
```

## Python install on Pi

The repo contents must already be present at `/opt/market_regime_v1` before running these commands.

```bash
sudo install -d /opt/market_regime_v1
sudo chown -R "$USER":"$USER" /opt/market_regime_v1
cd /opt/market_regime_v1
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Pi systemd install

```bash
cd /opt/market_regime_v1
sudo cp deploy/systemd/research_os_pi_cycle.service /etc/systemd/system/
sudo cp deploy/systemd/research_os_pi_cycle.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now research_os_pi_cycle.timer
```

## Desktop PC worker start

Run this on the desktop PC in PowerShell, from the repo clone that will hold the heavy-validation artifacts:

```powershell
$env:OPENAI_API_KEY="replace_with_real_key"
$env:REDIS_URL="redis://<PI_LAN_IP>:6379/0"
$env:RESEARCH_OS_ROOT="C:\Users\benda\Desktop\market_regime_v1"
Set-Location C:\Users\benda\Desktop\market_regime_v1
.\.venv\Scripts\python.exe -B -m services.pc.worker_service --config configs/runtime/runtime_config.pc_worker.template.json --run-pc-worker-consumer
```

## First validation sequence

On the Pi:

```bash
cd /opt/market_regime_v1
set -a
. /etc/default/research_os
set +a
.venv/bin/python -B -m services.pi.ingest_service --config configs/runtime/runtime_config.pi_orchestrator.template.json --health
.venv/bin/python -B -m services.pi.ingest_service --config configs/runtime/runtime_config.pi_orchestrator.template.json --family-registry configs/families/family_registry.template.json --status
```

On the desktop PC:

```powershell
$env:OPENAI_API_KEY="replace_with_real_key"
$env:REDIS_URL="redis://<PI_LAN_IP>:6379/0"
$env:RESEARCH_OS_ROOT="C:\Users\benda\Desktop\market_regime_v1"
Set-Location C:\Users\benda\Desktop\market_regime_v1
.\.venv\Scripts\python.exe -B -m services.pc.worker_service --config configs/runtime/runtime_config.pc_worker.template.json --health
.\.venv\Scripts\python.exe -B -m services.pc.worker_service --config configs/runtime/runtime_config.pc_worker.template.json --status
```

With the desktop worker still running, on the Pi run the first real cycle:

```bash
sudo systemctl start research_os_pi_cycle.service
sudo systemctl status research_os_pi_cycle.service --no-pager
sudo systemctl status research_os_pi_cycle.timer --no-pager
sudo journalctl -u research_os_pi_cycle.service -n 100 --no-pager
```

On the desktop PC, confirm a heavy-validation artifact was written:

```powershell
Get-ChildItem C:\Users\benda\Desktop\market_regime_v1\outputs\research_os\dev_only\mvp\artifacts\heavy_validation_outputs |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 FullName,LastWriteTime
```

## Rollback

On the Pi:

```bash
sudo systemctl disable --now research_os_pi_cycle.timer
sudo systemctl stop research_os_pi_cycle.service
sudo rm -f /etc/systemd/system/research_os_pi_cycle.service
sudo rm -f /etc/systemd/system/research_os_pi_cycle.timer
sudo systemctl daemon-reload
sudo systemctl reset-failed
```

To stop Redis on the Pi:

```bash
sudo systemctl disable --now redis-server
```

On the desktop PC:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -eq 'python.exe' -and
    $_.CommandLine -like '*services.pc.worker_service*--run-pc-worker-consumer*'
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Authority publish bridge for deployed app input

The deployed app input is repo content, not an implicit side channel:

- `app.py` resolves authority inputs as repo-relative files under `outputs/execution/authority/`
- the current project publish mechanism that reaches deployed app source content is `git push origin main`
- therefore the Pi authority producer must publish the two authority files into repo `main`

No app consumer cutover happens here. This is manual producer-side publishing only.

Use this exact first-run Pi environment and entrypoint for authoritative production publishing:

```bash
cd /opt/market_regime_v1
export MRV1_AUTHORITY_REPO_REMOTE=origin
export MRV1_AUTHORITY_REPO_BRANCH=main
export MRV1_AUTHORITY_PUBLISH_TREE=/opt/market_regime_v1__authority_publish
export MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS=3
export MRV1_AUTHORITY_GIT_USER_NAME="MRV1 Pi Authority Publisher"
export MRV1_AUTHORITY_GIT_USER_EMAIL="mrv1-pi-authority@example.com"
.venv/bin/python scripts/execution/run_pi_authoritative_producer.py
```

What it does:

- validates and publishes existing app/status artifacts through the safe default `scripts/execution/run_pi_authoritative_producer.py`
- runs the long refresh chain only when `--mode full-refresh` is explicitly passed
- writes `outputs/execution/authority/latest_attempt_status.json`
- writes `outputs/execution/authority/latest_successful_snapshot.json` on success
- resolves the runtime checkout remote URL but does not push from the runtime checkout
- bootstraps or reuses a dedicated clean publish clone at `MRV1_AUTHORITY_PUBLISH_TREE`
- fetches `origin/main` into that clean publish clone, checks out `main`, hard-resets to `origin/main`, and cleans untracked files
- copies only the two authority files into the clean publish clone
- commits and pushes only from that clean publish clone
- retries from a fresh fetch/reset if `git push` is rejected by remote drift

Exact validation commands on the Pi after the first publish:

```bash
cd /opt/market_regime_v1
export MRV1_AUTHORITY_REPO_REMOTE=origin
export MRV1_AUTHORITY_REPO_BRANCH=main
export MRV1_AUTHORITY_PUBLISH_TREE=/opt/market_regime_v1__authority_publish
export MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS=3
export MRV1_AUTHORITY_GIT_USER_NAME="MRV1 Pi Authority Publisher"
export MRV1_AUTHORITY_GIT_USER_EMAIL="mrv1-pi-authority@example.com"
.venv/bin/python scripts/execution/run_pi_authoritative_producer.py
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" status --short
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" log -1 --stat -- outputs/execution/authority/latest_attempt_status.json outputs/execution/authority/latest_successful_snapshot.json
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" show --pretty= --name-only HEAD
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" show HEAD:outputs/execution/authority/latest_attempt_status.json
git -C "$MRV1_AUTHORITY_PUBLISH_TREE" show HEAD:outputs/execution/authority/latest_successful_snapshot.json
git -C /opt/market_regime_v1 status --short
```

Exact rollback for the last authority publish commit:

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
