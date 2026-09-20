# Multi-asset rotation v1 preregistration

No candidate has been evaluated. The twelve-asset availability/quality inventory
is in multi-asset-input-quality-20260920.json. Exact genes, domains, initial ten,
seed 20260921, folds, costs and verdict rules are frozen in
research_os/dev_only/multi_asset/study.json and CONTRACT.md before implementation.

Universe: ADA, AVAX, BNB, BTC, DOGE, DOT, ETH, LINK, LTC, SOL, TRX, XRP (USDT pairs).
Warmup begins 2021-01-01; train 2021-08-01..2022-12-30; validation windows
2023-01-01..2023-12-30 and 2024-01-01..2024-12-30; final
2025-01-01..2026-08-19. Each window liquidates next calendar day open. Final is
retrospective, already-seen history; it is never independent promotion evidence.

Read-only Pi preflight: production HEAD 1bb2d0d64363d111d92e4257d0a7345b484b8532,
125 dirty entries with unchanged status hash and all three production control
hashes matching the installation audit. Production inactive/success, production
timer enabled/active, no pending jobs. Research worker inactive, queue empty,
three installed research-unit hashes unchanged. Free disk 2,158,919,680 bytes;
the safety reserve remains satisfied. All twelve CSV files end 2026-09-19 and
have complete valid coverage of the locked study slice.

The latest user request authorizes one new pinned release, research-only unit
pin updates and exactly one queued study if these safety assumptions hold.
No additional installation approval is required within that scope. This commit
is preregistration only; implementation and any evaluation must follow it.
