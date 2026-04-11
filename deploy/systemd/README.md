# Research OS systemd templates

These unit files are deployment templates for the dev-only Research OS MVP runtime.
They do not add live trading logic, source_of_truth writes, or promotion logic.

## Profiles

- `safe_local_smoke`: `configs/runtime/runtime_config.template.json`, memory queue, full pipeline disabled by default.
- `pi_orchestrator`: `configs/runtime/runtime_config.pi_orchestrator.template.json`, Redis Streams queue backend, full pipeline disabled by default, paused/stopped family override disabled.
- `pc_worker`: `configs/runtime/runtime_config.pc_worker.template.json`, Redis Streams queue backend, consumes `research_os:heavy_validation_jobs`.

## Units

- `research_os_pi_cycle.service`: runs one Pi orchestrator cycle and exits.
- `research_os_pi_cycle.timer`: starts the Pi cycle service after boot and then every 30 minutes.
- `research_os_pc_worker.service`: runs the PC heavy-validation worker consumer until stopped.

## Install sketch

Adjust `WorkingDirectory`, Python path, and config paths for the target machine before installing.

```bash
sudo cp deploy/systemd/research_os_pi_cycle.service /etc/systemd/system/
sudo cp deploy/systemd/research_os_pi_cycle.timer /etc/systemd/system/
sudo cp deploy/systemd/research_os_pc_worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now research_os_pi_cycle.timer
sudo systemctl enable --now research_os_pc_worker.service
```

Use the smoke profile locally unless Redis is available and the Pi/PC pair should communicate through the configured streams.
