from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.hyperliquid_credentials import (  # noqa: E402
    get_account_setup,
    redact_sensitive_text,
    validate_account_setup_authorization,
)
from scripts.execution.hyperliquid_live_canary import (  # noqa: E402
    fetch_extra_agents,
    fetch_user_role,
    require_crypto_deps,
)


ACCOUNT_CONFIG_PATH = ROOT / "execution/config/hyperliquid_account.json"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("hyperliquid_account_config_not_object")
    return payload


def validate_production_signer(
    *,
    account_config_path: Path = ACCOUNT_CONFIG_PATH,
    environ: Mapping[str, str] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    account_cfg = read_json(account_config_path)
    crypto = require_crypto_deps()
    account_setup = get_account_setup(account_cfg, crypto, environ=environ)
    return validate_account_setup_authorization(
        account_cfg=account_cfg,
        account_setup=account_setup,
        fetch_user_role=fetch_user_role,
        fetch_extra_agents=fetch_extra_agents,
        environ=environ,
        now_ms=now_ms,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the production Hyperliquid systemd credential and named-agent authorization."
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the pass marker; the signer secret is never printed in either mode.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_production_signer()
    except BaseException as exc:
        safe_error = redact_sensitive_text(exc)
        print(json.dumps({"status": "FAIL", "error": safe_error}, sort_keys=True))
        return 1
    if args.quiet:
        print("SIGNER_VALIDATION=PASS")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
