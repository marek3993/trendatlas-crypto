from __future__ import annotations

import os
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


TRENDATLAS_MASTER_ACCOUNT = "0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856"
TRENDATLAS_AGENT_NAME = "TrendAtlasProd"
SYSTEMD_CREDENTIAL_NAME = "hyperliquid-agent-private-key"
SYSTEMD_ENCRYPTED_CREDENTIAL_PATH = Path(
    "/etc/credstore.encrypted/mrv1-production.hyperliquid-agent-private-key"
)

_CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_PRIVATE_KEY_RE = re.compile(r"(?i)(?<![0-9a-f])(?:0x)?[0-9a-f]{64}(?![0-9a-f])")
_ENV_SECRET_RE = re.compile(r"(?i)(HYPERLIQUID_SECRET_KEY\s*=\s*)[^\s,;]+")


class SignerCredentialError(RuntimeError):
    pass


class SignerValidationError(RuntimeError):
    pass


def redact_sensitive_text(value: Any, *, known_secrets: tuple[str, ...] = ()) -> str:
    """Return an error/log-safe string that cannot contain a signer private key."""
    rendered = str(value)
    for secret in sorted((item for item in known_secrets if item), key=len, reverse=True):
        rendered = rendered.replace(secret, "[REDACTED_PRIVATE_KEY]")
        if secret.startswith("0x"):
            rendered = rendered.replace(secret[2:], "[REDACTED_PRIVATE_KEY]")
    rendered = _ENV_SECRET_RE.sub(r"\1[REDACTED_PRIVATE_KEY]", rendered)
    return _PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", rendered)


def _credential_name(account_cfg: Mapping[str, Any], environ: Mapping[str, str]) -> str:
    configured = str(account_cfg.get("credential_name") or SYSTEMD_CREDENTIAL_NAME).strip()
    service_name = str(environ.get("MRV1_HYPERLIQUID_CREDENTIAL_NAME") or configured).strip()
    if configured != service_name:
        raise SignerCredentialError("systemd_credential_name_mismatch")
    if not _CREDENTIAL_NAME_RE.fullmatch(configured):
        raise SignerCredentialError("invalid_systemd_credential_name")
    return configured


def _reject_insecure_sources(account_cfg: Mapping[str, Any]) -> None:
    forbidden = {
        "secret_key": account_cfg.get("secret_key"),
        "secret_key_env": account_cfg.get("secret_key_env"),
        "keystore_path": account_cfg.get("keystore_path"),
    }
    configured = [name for name, value in forbidden.items() if str(value or "").strip()]
    if configured:
        raise SignerCredentialError(
            "insecure_signer_source_forbidden:" + ",".join(sorted(configured))
        )


def load_secret_key(
    account_cfg: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Load the signer only from systemd's per-unit credential directory."""
    env = os.environ if environ is None else environ
    _reject_insecure_sources(account_cfg)
    name = _credential_name(account_cfg, env)
    directory_raw = str(env.get("CREDENTIALS_DIRECTORY") or "").strip()
    if not directory_raw:
        raise SignerCredentialError("systemd_credentials_directory_missing")
    directory = Path(directory_raw)
    if not directory.is_absolute():
        raise SignerCredentialError("systemd_credentials_directory_not_absolute")
    path = directory / name
    try:
        lst = path.lstat()
    except FileNotFoundError as exc:
        raise SignerCredentialError("systemd_signer_credential_missing") from exc
    if stat.S_ISLNK(lst.st_mode) or not stat.S_ISREG(lst.st_mode):
        raise SignerCredentialError("systemd_signer_credential_not_regular_file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                lst.st_dev,
                lst.st_ino,
            ):
                raise SignerCredentialError("systemd_signer_credential_changed_during_open")
            raw = os.read(descriptor, 513)
        finally:
            os.close(descriptor)
    except SignerCredentialError:
        raise
    except OSError as exc:
        raise SignerCredentialError("systemd_signer_credential_unreadable") from exc
    if len(raw) > 512:
        raise SignerCredentialError("systemd_signer_credential_too_large")
    try:
        secret = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise SignerCredentialError("systemd_signer_credential_not_ascii") from exc
    normalized = secret if secret.startswith("0x") else f"0x{secret}"
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", normalized):
        raise SignerCredentialError("systemd_signer_credential_invalid_private_key_shape")
    return normalized


def validate_configured_master_account(
    account_cfg: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    configured = str(account_cfg.get("account_address") or "").strip()
    service_expected = str(
        env.get("MRV1_HYPERLIQUID_ACCOUNT_ADDRESS") or TRENDATLAS_MASTER_ACCOUNT
    ).strip()
    if service_expected.lower() != TRENDATLAS_MASTER_ACCOUNT.lower():
        raise SignerValidationError("service_master_account_contract_mismatch")
    if configured.lower() != TRENDATLAS_MASTER_ACCOUNT.lower():
        raise SignerValidationError("configured_master_account_contract_mismatch")
    return TRENDATLAS_MASTER_ACCOUNT


def get_account_setup(
    account_cfg: Mapping[str, Any],
    crypto: Any,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    account_address = validate_configured_master_account(account_cfg, environ=environ)
    secret_key = load_secret_key(account_cfg, environ=environ)
    try:
        wallet = crypto.Account.from_key(secret_key)
    except BaseException:
        raise SignerCredentialError("signer_private_key_invalid") from None
    signer_address = str(wallet.address)
    vault_address = str(account_cfg.get("vault_address") or "").strip() or None
    return {
        "wallet": wallet,
        "signer_address": signer_address,
        "account_address": account_address,
        "vault_address": vault_address,
        "uses_agent_wallet": signer_address.lower() != account_address.lower(),
        "credential_name": _credential_name(
            account_cfg, os.environ if environ is None else environ
        ),
    }


def _role_name(role_response: Any) -> str:
    if isinstance(role_response, Mapping):
        return str(role_response.get("role") or "").strip()
    return str(role_response or "").strip()


def _valid_until_utc(valid_until_ms: int) -> str:
    return (
        datetime.fromtimestamp(valid_until_ms / 1000, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_account_setup_authorization(
    *,
    account_cfg: Mapping[str, Any],
    account_setup: Mapping[str, Any],
    fetch_user_role: Callable[[str], Any],
    fetch_extra_agents: Callable[[str], list[dict[str, Any]]],
    environ: Mapping[str, str] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    expected_account = validate_configured_master_account(account_cfg, environ=env)
    expected_name = str(
        env.get("MRV1_HYPERLIQUID_AGENT_NAME") or TRENDATLAS_AGENT_NAME
    ).strip()
    if expected_name != TRENDATLAS_AGENT_NAME:
        raise SignerValidationError("service_agent_name_contract_mismatch")
    configured_name = str(account_cfg.get("agent_name") or "").strip()
    if configured_name != TRENDATLAS_AGENT_NAME:
        raise SignerValidationError("configured_agent_name_contract_mismatch")
    signer_address = str(account_setup.get("signer_address") or "").strip()
    setup_account = str(account_setup.get("account_address") or "").strip()
    reasons: list[str] = []
    if setup_account.lower() != expected_account.lower():
        reasons.append("signer_setup_master_account_mismatch")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", signer_address):
        reasons.append("derived_signer_address_invalid")
    if signer_address.lower() == expected_account.lower():
        reasons.append("master_wallet_private_key_forbidden_use_agent_wallet")

    role_response = fetch_user_role(expected_account)
    role = _role_name(role_response)
    if role.lower() != "user":
        reasons.append("configured_account_role_not_user")
    extra_agents = fetch_extra_agents(expected_account)
    matching_address = [
        row
        for row in extra_agents
        if str(row.get("address") or "").strip().lower() == signer_address.lower()
    ]
    if not matching_address:
        reasons.append("derived_signer_not_authorized_for_master_account")
    matching_named = [
        row
        for row in matching_address
        if str(row.get("name") or "").strip() == expected_name
    ]
    if matching_address and not matching_named:
        reasons.append("derived_signer_authorized_under_wrong_agent_name")

    valid_until_ms: int | None = None
    if matching_named:
        try:
            valid_until_ms = int(matching_named[0].get("validUntil"))
        except (TypeError, ValueError):
            reasons.append("agent_authorization_expiry_missing")
    checked_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if valid_until_ms is not None and valid_until_ms <= checked_at_ms:
        reasons.append("agent_authorization_expired")
    if reasons:
        raise SignerValidationError("signer_validation_failed:" + ",".join(reasons))

    assert valid_until_ms is not None
    return {
        "status": "PASS",
        "credential_present": True,
        "credential_value_exposed": False,
        "credential_name": str(account_setup.get("credential_name") or SYSTEMD_CREDENTIAL_NAME),
        "credential_mechanism": "systemd_LoadCredentialEncrypted_host_key",
        "account_address": expected_account,
        "account_role": role,
        "signer_address": signer_address,
        "uses_agent_wallet": True,
        "agent_name": expected_name,
        "signer_authorized": True,
        "valid_until_ms": valid_until_ms,
        "valid_until_utc": _valid_until_utc(valid_until_ms),
        "authorization_days_remaining": round(
            (valid_until_ms - checked_at_ms) / 86_400_000, 3
        ),
    }
