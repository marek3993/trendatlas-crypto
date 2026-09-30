"""Isolated Python entrypoint for systemd's -I mode."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

if len(sys.argv)>1 and sys.argv[1]=="broker":
    sys.argv.pop(1)
    from research.phase2_continuous.broker import main
else:
    from research.phase2_continuous.runtime import main

main()
