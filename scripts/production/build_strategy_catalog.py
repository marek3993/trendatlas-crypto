from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_catalog_common import (
    DEFAULT_OUTPUT_PATH,
    build_strategy_catalog_payload,
    validate_strategy_catalog_payload,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Production Core strategy catalog.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_strategy_catalog_payload()
    validation = validate_strategy_catalog_payload(payload)
    if validation["status"] != "passed":
        raise SystemExit(
            "Strategy catalog build blocked fail-closed:\n- " + "\n- ".join(validation["errors"])
        )
    write_json_atomic(args.output_path, payload)
    print(
        json.dumps(
            {
                "output_path": str(args.output_path.resolve()),
                "strategy_count": len(payload["strategies"]),
                "current_official_strategy_model": payload["current_official_strategy_model"],
                "validation_status": validation["status"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
