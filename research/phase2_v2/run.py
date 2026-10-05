"""Isolated -I entrypoint."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
if len(sys.argv)>1 and sys.argv[1]=='broker':
    sys.argv.pop(1)
    from research.phase2_v2.broker import main
else:
    from research.phase2_v2.runtime import main
main()
