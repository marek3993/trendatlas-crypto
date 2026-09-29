"""Create an independent workspace then run the canonical no-submit orchestrator."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.execution.rehearsal_workspace import create_rehearsal, runtime_fingerprints


def main() -> int:
    state = Path('/var/lib/trendatlas-production/rehearsal')
    stage = state / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    manifest = create_rehearsal(ROOT, stage)
    # Immutable third-party modules can be shared, never runtime/data/account files.
    (stage/'web/node_modules').symlink_to(ROOT/'web/node_modules', target_is_directory=True)
    env = dict(os.environ, MRV1_MULTI_ACCOUNT_WEB_ROOT=str(stage/'web'),
               MRV1_AUTOMATIC_PRODUCER_ID='canonical_production_host')
    result = subprocess.run([sys.executable, str(stage/'scripts/execution/run_trendatlas_production.py'), '--no-submit'],
                            cwd=stage, env=env, check=False)
    unchanged = manifest['files'] == runtime_fingerprints(ROOT)
    evidence = {'staging_root':str(stage), 'returncode':result.returncode, 'canonical_files_unchanged':unchanged}
    (state/'latest.json').write_text(json.dumps(evidence,indent=2)+'\n')
    if not unchanged: raise RuntimeError('canonical runtime changed during rehearsal; inspect other producer activity')
    return result.returncode

if __name__ == '__main__': raise SystemExit(main())
