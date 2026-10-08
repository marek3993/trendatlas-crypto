"""Standalone systemd entrypoint under Python -I."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if sys.argv[1] == 'worker':
    sys.argv.pop(1)
    from research.anomaly_lab.runtime import main
    main()
elif sys.argv[1] == 'broker':
    import argparse
    from research.anomaly_lab.broker import once
    p = argparse.ArgumentParser(); p.add_argument('command'); p.add_argument('--mailbox', type=Path, required=True)
    a = p.parse_args(); print({'processed': once(a.mailbox)})
else: raise ValueError('unknown_lab_command')
