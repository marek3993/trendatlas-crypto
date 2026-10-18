"""Standalone Clean 50/50 dry-run entrypoint. Never imports the live executor."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from trendatlas_clean.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
