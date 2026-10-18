"""Download the frozen 59-symbol reference without production data access."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from trendatlas_clean.fetch_data import main

if __name__ == "__main__":
    raise SystemExit(main())
