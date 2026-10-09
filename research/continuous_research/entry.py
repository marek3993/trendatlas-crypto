import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import argparse
from research.continuous_research.common import canonical

p=argparse.ArgumentParser();p.add_argument('mode',choices=('worker','broker','audit'))
p.add_argument('--root',type=Path);p.add_argument('--mailbox',type=Path,required=True)
p.add_argument('--inputs',type=Path);p.add_argument('--bootstrap',type=Path)
a=p.parse_args()
if a.mode=='broker':
    from research.continuous_research.broker import once
    print(canonical({'state':once(a.mailbox)}))
else:
    from research.continuous_research.runtime import run,audit
    print(canonical(audit(a.root,a.mailbox) if a.mode=='audit' else run(a.root,a.mailbox,a.inputs,a.bootstrap)))
