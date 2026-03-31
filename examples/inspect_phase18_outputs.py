from pathlib import Path
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

FILES = [
    OUTPUTS_DIR / "phase18_always_daily.csv",
    OUTPUTS_DIR / "phase18_soft_kill_4h.csv",
]


def main() -> None:
    for path in FILES:
        print("\n" + "=" * 100)
        print(path)
        if not path.exists():
            print("CHÝBA")
            continue

        df = pd.read_csv(path)
        print(f"rows={len(df)}")
        print("columns:")
        for c in df.columns.tolist():
            print(f"  - {c}")

        print("\nhead:")
        print(df.head(5).to_string(index=False))

        print("\nnon-null counts:")
        print(df.notna().sum().to_string())


if __name__ == "__main__":
    main()