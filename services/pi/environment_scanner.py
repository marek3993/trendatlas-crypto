from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from services.shared.artifact_writer import ArtifactWriter
from services.shared.schemas import EnvironmentScan, RuntimeConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return RuntimeConfig.from_mapping(payload)


def scan_environment(config: RuntimeConfig, project_root: Path = PROJECT_ROOT) -> EnvironmentScan:
    safe_environment = {key: os.environ.get(key, "") for key in config.scanner_env_keys}
    notes = [
        "dev_only_research_os_scan",
        "no_live_trading_logic",
        "source_of_truth_not_mutated",
    ]
    return EnvironmentScan.collect(
        scanner_id="pi_environment_scanner",
        role=config.role,
        project_root=project_root,
        paths=config.scanner_paths,
        environment=safe_environment,
        notes=notes,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pi environment scanner skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--write", action="store_true", help="Write scan JSON under artifact_root.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    scan = scan_environment(config)
    if args.write:
        writer = ArtifactWriter(config.artifact_root)
        record = writer.write_json("environment/latest_environment_scan.json", scan.to_dict())
        print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    else:
        print(json.dumps(scan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
