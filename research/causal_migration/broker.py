"""Frozen JSON-only broker; no datasets, results, production access or order SDK."""
import os
from pathlib import Path
import sys
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runtime as r
r.legacy.load_engine(r.ENGINE)
from research.causal_evolution.mailbox import Mailbox
from research.causal_evolution.locking import WorkerLock
from research.causal_evolution.designer import broker_once
root=Path('/var/lib/trendatlas-research-broker/mailbox')
with WorkerLock(root/'broker.lock'):
    mail=Mailbox(root)
    try:broker_once(mail)
    finally:mail.close()
