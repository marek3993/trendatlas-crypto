"""Local-only interface; no root override, production path or scheduler option."""
import argparse
import json

from .controller import ROOT, export_report, initialize, load_study, report, step


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--input", required=True)
    sub.add_parser("step")
    sub.add_parser("report")
    sub.add_parser("export")
    args = parser.parse_args()
    run_id = load_study()["experiment_id"]
    if args.command == "init":
        result = initialize(ROOT, run_id, args.input)
    elif args.command == "step":
        result = step(ROOT, run_id)
        result = {"generation": result["meta"]["completed_generations"],
                  "eligible": len(result["generation"]["ranking"]), "meta": result["meta"]}
    elif args.command == "export":
        result = {"report": str(export_report(ROOT, run_id))}
    else:
        result = report(ROOT, run_id)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
