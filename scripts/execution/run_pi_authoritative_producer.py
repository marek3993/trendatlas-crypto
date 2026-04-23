from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SCRIPT = ROOT / "scripts" / "daily_refresh_app_pipeline.py"


def build_pi_authoritative_env() -> dict[str, str]:
    env = os.environ.copy()
    env["MRV1_ENABLE_AUTHORITY_PUBLISH"] = "1"
    env["MRV1_AUTHORITY_MODE"] = "authoritative"
    env["MRV1_AUTOMATIC_PRODUCER_ID"] = "raspberry_pi"
    env["MRV1_REQUIRE_PI_RUNTIME"] = "1"
    env.setdefault("MRV1_PUBLISH_HOSTNAME", socket.gethostname())
    env["MRV1_AUTHORITY_ENTRYPOINT"] = str(Path(__file__).resolve())
    return env


def main() -> None:
    if not PIPELINE_SCRIPT.exists():
        raise FileNotFoundError(f"Missing pipeline script: {PIPELINE_SCRIPT}")

    command = [sys.executable, str(PIPELINE_SCRIPT), *sys.argv[1:]]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        env=build_pi_authoritative_env(),
        check=False,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
