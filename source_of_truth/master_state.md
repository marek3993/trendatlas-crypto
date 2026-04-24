# Master State

## Official state snapshot
- Official core production baseline: `phase66g_production_soft_filters`
- Official universe winner: `phase67j_no_neo_main`
- Current live/app truth: `phase68g_66g_1p25x_candidate`
- Current app main strategy model: `phase68g_66g_1p25x_candidate`
- Reference strategy model: `phase67j_no_neo_main`
- Benchmark: `BTC`

## Production authority model
- Jediný automatický production producer: `raspberry_pi`
- PC rola: `manual_recovery_debug_only`
- GitHub Actions rola: `validation_only`
- App authority source je dvoj-súborový model:
  - `outputs/execution/authority/latest_successful_snapshot.json`
  - `outputs/execution/authority/latest_attempt_status.json`

## Legacy paths are not app authority
- `outputs/execution/app_snapshot/*`
- `outputs/app_refresh_pipeline/*`
- `outputs/execution/full_auto_scheduler/*`
- `outputs/execution/runtime_health/*`
- `outputs/execution/live_status/*`

## Authority rules
- `latest_successful_snapshot.json` je posledný úspešný autoritatívny snapshot.
- `latest_attempt_status.json` je posledný autoritatívny attempt status.
- Failed attempt nesmie prepísať posledný úspešný snapshot.
- App a všetky MRV1 chaty majú reasonovať z Pi-authority modelu, nie z legacy PC/refresh snapshotov.