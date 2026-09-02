from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.hyperliquid_credentials import (  # noqa: E402
    SYSTEMD_CREDENTIAL_NAME,
    SYSTEMD_ENCRYPTED_CREDENTIAL_PATH,
    redact_sensitive_text,
)


def run_checked(command: list[str], *, stdin: bytes | None = None) -> bytes:
    completed = subprocess.run(
        command,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", errors="replace").strip()
            or completed.stdout.decode("utf-8", errors="replace").strip()
        )
        raise RuntimeError(
            redact_sensitive_text(
                f"credential_command_failed:{Path(command[0]).name}:returncode={completed.returncode}:{detail}"
            )
        )
    return completed.stdout


def validate_backend() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("must_run_as_root")
    run_checked(["systemd-creds", "setup"])
    dummy = "0x" + secrets.token_hex(32)
    try:
        with tempfile.TemporaryDirectory(prefix="mrv1-systemd-creds-", dir="/tmp") as temp_dir:
            encrypted = Path(temp_dir) / SYSTEMD_ENCRYPTED_CREDENTIAL_PATH.name
            run_checked(
                [
                    "systemd-creds",
                    "encrypt",
                    "--with-key=host",
                    "--newline=no",
                    f"--name={SYSTEMD_CREDENTIAL_NAME}",
                    "-",
                    str(encrypted),
                ],
                stdin=dummy.encode("ascii"),
            )
            run_checked(
                [
                    "systemd-run",
                    "--quiet",
                    "--wait",
                    "--collect",
                    f"--unit=mrv1-systemd-credential-check-{os.getpid()}",
                    f"--property=LoadCredentialEncrypted={SYSTEMD_CREDENTIAL_NAME}:{encrypted}",
                    "/bin/sh",
                    "-c",
                    f'test -s "$CREDENTIALS_DIRECTORY/{SYSTEMD_CREDENTIAL_NAME}"',
                ]
            )
            decrypted = run_checked(
                [
                    "systemd-creds",
                    "decrypt",
                    "--newline=no",
                    f"--name={SYSTEMD_CREDENTIAL_NAME}",
                    str(encrypted),
                    "-",
                ]
            ).decode("ascii")
            if decrypted != dummy:
                raise RuntimeError("systemd_credential_roundtrip_mismatch")
    finally:
        dummy = "[cleared]"


def derive_signer_address(secret: str) -> str:
    try:
        from eth_account import Account

        return str(Account.from_key(secret).address)
    except BaseException as exc:
        raise RuntimeError("private_key_could_not_derive_signer_address") from exc


def provision(*, replace: bool = False) -> str:
    if os.geteuid() != 0:
        raise RuntimeError("must_run_as_root")
    destination = SYSTEMD_ENCRYPTED_CREDENTIAL_PATH
    if destination.exists() and not replace:
        raise RuntimeError("encrypted_credential_already_exists_use_explicit_replace_for_rotation")
    secret = getpass.getpass("Hyperliquid API wallet private key (hidden): ").strip()
    normalized = secret if secret.startswith("0x") else f"0x{secret}"
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", normalized):
        raise RuntimeError("private_key_shape_invalid")
    signer_address = derive_signer_address(normalized)

    old_umask = os.umask(0o077)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        run_checked(["systemd-creds", "setup"])
        run_checked(
            [
                "systemd-creds",
                "encrypt",
                "--with-key=host",
                "--newline=no",
                f"--name={SYSTEMD_CREDENTIAL_NAME}",
                "-",
                str(temporary),
            ],
            stdin=normalized.encode("ascii"),
        )
        os.chmod(temporary, 0o400)
        os.chown(temporary, 0, 0)
        os.replace(temporary, destination)
        os.chmod(destination, 0o400)
        os.chown(destination, 0, 0)
    finally:
        os.umask(old_umask)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        normalized = "[cleared]"
        secret = "[cleared]"
    return signer_address


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read a Hyperliquid API-wallet private key once through hidden local input and store "
            "only a host-key-encrypted systemd credential."
        )
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Explicitly rotate an existing encrypted credential after a new API wallet is authorized.",
    )
    parser.add_argument(
        "--check-backend",
        action="store_true",
        help="Initialize the systemd host key and verify a random in-memory encrypted round trip without prompting for a real credential.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.check_backend:
            validate_backend()
            print("SYSTEMD_CREDENTIAL_BACKEND=PASS")
            return 0
        signer_address = provision(replace=args.replace)
    except BaseException as exc:
        print(f"PROVISIONING=FAIL reason={redact_sensitive_text(exc)}", file=sys.stderr)
        return 1
    print("PROVISIONING=PASS")
    print(f"SIGNER_ADDRESS={signer_address}")
    print(f"ENCRYPTED_CREDENTIAL={SYSTEMD_ENCRYPTED_CREDENTIAL_PATH}")
    print("PRIVATE_KEY_DISPLAYED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
