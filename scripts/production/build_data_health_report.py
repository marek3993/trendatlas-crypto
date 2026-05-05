from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.data_health_common import (
    DEFAULT_OUTPUT_DIR,
    ROOT,
    build_report_bundle,
    parse_key_value_pairs,
    parse_reference_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build centralized MRV1 data health report.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reference-now-utc", type=str, default="")
    parser.add_argument(
        "--source-path-override",
        action="append",
        default=[],
        help="Override source path for a specific source_id using source_id=path.",
    )
    parser.add_argument(
        "--env-source-override",
        action="append",
        default=[],
        help="Override env-backed source presence/value using source_id=value. Empty value means unavailable.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = build_report_bundle(
        root=ROOT,
        output_dir=args.output_dir,
        reference_now=parse_reference_now(args.reference_now_utc),
        path_overrides=parse_key_value_pairs(list(args.source_path_override)),
        env_overrides=parse_key_value_pairs(list(args.env_source_override)),
        write_outputs=True,
    )
    print(json.dumps(bundle["report"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
