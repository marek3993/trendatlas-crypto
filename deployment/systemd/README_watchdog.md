# MRV1 Watchdog systemd templates

These files are repo-side templates only. They are not installed automatically.

## Included files

- `mrv1-watchdog.service`
- `mrv1-watchdog.timer`

The timer uses `OnCalendar=*-*-* *:25:00 UTC`, which is a safe equivalent to "00:25 UTC plus hourly" and avoids colliding with the existing `00:10 UTC` daily runtime timer.

## Validation commands

Run these from the repo checkout before installing the unit:

```bash
python -m py_compile scripts/execution/mrv1_self_healing_watchdog.py
python scripts/execution/mrv1_self_healing_watchdog.py --check-only --json
```

## Suggested install flow

Copy the templates into `/etc/systemd/system/` on the target host, then reload and enable them:

```bash
sudo cp deployment/systemd/mrv1-watchdog.service /etc/systemd/system/
sudo cp deployment/systemd/mrv1-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mrv1-watchdog.timer
```

## Suggested post-install checks

```bash
systemctl cat mrv1-watchdog.service
systemctl cat mrv1-watchdog.timer
systemctl list-timers --all | grep mrv1-watchdog
journalctl -u mrv1-watchdog.service -n 100 --no-pager
```
