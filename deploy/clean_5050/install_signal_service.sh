#!/usr/bin/env bash
# Install only the isolated public-data signal producer; never enables a trader.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run as root on the VPS.' >&2
  exit 2
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
target=/opt/trendatlas-clean
id trendatlas-clean >/dev/null 2>&1 || useradd --system --home-dir /var/lib/trendatlas-clean --shell /usr/sbin/nologin trendatlas-clean
install -d "$target/src/trendatlas_clean" "$target/scripts/production" "$target/scripts/research" "$target/source_of_truth" "$target/tests/fixtures"
cp -R "$repo_root/src/trendatlas_clean/." "$target/src/trendatlas_clean/"
cp "$repo_root/scripts/production/run_clean_5050.py" "$target/scripts/production/"
cp "$repo_root/scripts/research/validate_clean_5050.py" "$target/scripts/research/"
cp "$repo_root/tests/fixtures/clean_5050_reference.py" "$repo_root/tests/fixtures/clean_5050_checkpoints.json" "$target/tests/fixtures/"
cp "$repo_root/source_of_truth/clean_5050_contract.json" "$repo_root/source_of_truth/clean_5050_asset_exclusions.json" "$target/source_of_truth/"
cp "$repo_root/requirements-clean-5050.txt" "$target/"
if [ ! -x "$target/.venv/bin/python" ]; then
  python3 -m venv "$target/.venv"
fi
"$target/.venv/bin/python" -m pip install --disable-pip-version-check -r "$target/requirements-clean-5050.txt"
install -d -o trendatlas-clean -g trendatlas-clean -m 0700 /var/lib/trendatlas-clean
install -m 0644 "$repo_root/deploy/systemd/trendatlas-clean-signal.service" /etc/systemd/system/
install -m 0644 "$repo_root/deploy/systemd/trendatlas-clean-signal.timer" /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/trendatlas-clean-signal.service /etc/systemd/system/trendatlas-clean-signal.timer
systemctl daemon-reload
systemctl enable --now trendatlas-clean-signal.timer
systemctl start --no-block trendatlas-clean-signal.service
echo 'SIGNAL_SERVICE_INSTALLED=true; LIVE_TRADER_INSTALLED=false; NO_WAITING_PERIOD=true'
