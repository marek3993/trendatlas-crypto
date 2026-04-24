# Current Issues

## Accepted current state
- Pi-only authority model is active.
- App authority source is the two-file model:
  - `outputs/execution/authority/latest_successful_snapshot.json`
  - `outputs/execution/authority/latest_attempt_status.json`
- Legacy snapshot/runtime/refresh paths are non-authoritative for app reasoning.

## Active operational focus
- Complete soak test for unattended Pi authority publishing.
- Monitor `latest_authoritative_attempt_status`, `currentness_status`, and target closed UTC day daily.
- Confirm no remaining app reasoning path depends on legacy app snapshot/runtime/refresh files.

## Explicitly non-authoritative legacy paths
- `outputs/execution/app_snapshot/*`
- `outputs/app_refresh_pipeline/*`
- `outputs/execution/full_auto_scheduler/*`
- `outputs/execution/runtime_health/*`
- `outputs/execution/live_status/*`

## Authority runtime posture
- Raspberry Pi is the only automatic production producer.
- PC is manual recovery/debug only.
- GitHub Actions is validation only.