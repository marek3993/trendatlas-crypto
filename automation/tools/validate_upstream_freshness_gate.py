from __future__ import annotations

import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"
DEFAULT_GATE_CONFIG = AUTOMATION_ROOT / "config" / "upstream_freshness_gate.json"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_pattern(pattern: str) -> str:
    p = Path(pattern)
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / pattern)


def latest_match(pattern: str) -> Path | None:
    matches = glob.glob(resolve_pattern(pattern))
    if not matches:
        return None
    matches = [Path(m) for m in matches]
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def age_hours(path: Path) -> float:
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (now_utc() - ts).total_seconds() / 3600.0


def main() -> None:
    config_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_GATE_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"Gate config not found: {config_path}")

    config = read_json(config_path)
    stages = config.get("stages", [])

    findings: list[str] = []
    errors: list[str] = []
    resolved: list[dict] = []

    prev_mtime = None

    for stage in stages:
        name = str(stage["name"])
        pattern = str(stage["glob"])
        max_age_hours = float(stage["max_age_hours"])

        latest = latest_match(pattern)
        if latest is None:
            errors.append(f"{name}: no file matched glob={pattern}")
            continue

        this_age = age_hours(latest)
        mtime = latest.stat().st_mtime

        findings.append(f"{name}: latest={latest} age_hours={this_age:.2f}")

        if this_age > max_age_hours:
            errors.append(f"{name}: stale age_hours={this_age:.2f} > max_age_hours={max_age_hours:.2f}")

        if prev_mtime is not None and mtime < prev_mtime:
            errors.append(f"{name}: older than previous upstream stage in ordered freshness chain")

        prev_mtime = mtime
        resolved.append(
            {
                "name": name,
                "path": str(latest),
                "age_hours": round(this_age, 4),
            }
        )

    chain_status = "healthy" if not errors else "broken"

    print(f"config={config_path}")
    print(f"chain_status={chain_status}")

    for item in resolved:
        print(f"finding={item['name']}: path={item['path']} age_hours={item['age_hours']}")

    for finding in findings:
        print(f"finding={finding}")

    for error in errors:
        print(f"error={error}")

    if chain_status != "healthy":
        sys.exit(1)


if __name__ == "__main__":
    main()