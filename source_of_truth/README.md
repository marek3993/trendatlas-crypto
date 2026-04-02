# Market Regime v1 - Source of Truth

Tento priečinok je centrálna source-of-truth vrstva projektu Market Regime v1.

## Human-readable súbory
- `master_state.md` = stručný aktuálny stav projektu
- `chat_roles.md` = hranice a roly segment chatov
- `current_issues.md` = otvorené blockers/issues

## Machine-readable súbory
- `project_truth.json` = hlavná oficiálna pravda projektu
- `live_truth.json` = live/source-of-truth vrstva pre aktuálny stav modelu
- `export_contract.json` = oficiálny export mapping pre app
- `paths_registry.json` = register dôležitých ciest
- `decisions_log.jsonl` = audit trail rozhodnutí
- `experiments_registry.csv` = registry experimentov

## Pravidlá
- Ak sa zmení official winner alebo baseline, najprv sa updateuje `project_truth.json`.
- Ak sa zmení app export mapping, updateuje sa `export_contract.json`.
- Ak sa zmenia oficiálne cesty, updateuje sa `paths_registry.json`.
- `master_state.md` má byť len stručné zhrnutie, nie kompletná história.
- Chaty majú najprv čítať túto vrstvu a až potom riešiť task.
