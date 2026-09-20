"""python -m research_os.dev_only.evolution --help"""
import argparse
import json
from pathlib import Path

from .controller import ROOT, evolve, export_report, finalize, initialize, status


def main():
    parser = argparse.ArgumentParser(description="Offline research only: ten candidates, six survivors, four mutations.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Freeze dataset, split dates and search budget")
    init.add_argument("run_id")
    init.add_argument("--input", required=True)
    for name in ("train-start", "train-end", "validation-end", "holdout-end"):
        init.add_argument("--" + name, required=True)
    init.add_argument("--generations", type=int, default=3)
    init.add_argument("--seed", type=int, default=20260920)
    init.add_argument("--cost-bps", type=float, default=15.0)
    init.add_argument("--max-seconds", type=float, default=300)
    init.add_argument("--evaluation-protocol", help="Versioned JSON with frozen chronological controls and seen-period disclosure")
    for command in ("step", "finalize", "status", "report"):
        sub.add_parser(command).add_argument("run_id")
    args = vars(parser.parse_args())
    command, run_id = args.pop("command"), args.pop("run_id")
    if command == "init":
        if args["evaluation_protocol"]:
            args["evaluation_protocol"] = json.loads(Path(args["evaluation_protocol"]).read_text(encoding="utf-8"))
        result = initialize(ROOT, run_id, args.pop("input"), **args)
    else:
        result = {"step": evolve, "finalize": finalize, "status": status, "report": export_report}[command](ROOT, run_id)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
