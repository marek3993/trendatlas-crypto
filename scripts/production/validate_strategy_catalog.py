from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_catalog_common import (
    DEFAULT_OUTPUT_PATH,
    read_json_required,
    validate_strategy_catalog_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the Production Core strategy catalog.")
    parser.add_argument("--catalog-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = read_json_required(args.catalog_path)
    validation = validate_strategy_catalog_payload(payload)
    print(json.dumps(validation, indent=2, ensure_ascii=False))
    if validation["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
