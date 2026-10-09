import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from research.phase2_v2.market import canonical
from research.discovery_evolution.runtime import run, audit

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--inputs',type=Path);p.add_argument('--bootstrap',type=Path);p.add_argument('--audit',action='store_true')
a=p.parse_args();print(canonical(audit(a.root) if a.audit else run(a.root,a.inputs,a.bootstrap)))
