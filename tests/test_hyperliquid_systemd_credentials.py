from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.execution.hyperliquid_credentials import (
    SYSTEMD_CREDENTIAL_NAME,
    TRENDATLAS_AGENT_NAME,
    TRENDATLAS_MASTER_ACCOUNT,
    SignerCredentialError,
    SignerValidationError,
    get_account_setup,
    load_secret_key,
    redact_sensitive_text,
    validate_account_setup_authorization,
)


class FakeWallet:
    address = "0x1111111111111111111111111111111111111111"


class FakeAccount:
    @staticmethod
    def from_key(_secret: str) -> FakeWallet:
        return FakeWallet()


class FakeCrypto:
    Account = FakeAccount


def secure_config() -> dict:
    return {
        "credential_name": SYSTEMD_CREDENTIAL_NAME,
        "account_address": TRENDATLAS_MASTER_ACCOUNT,
        "agent_name": TRENDATLAS_AGENT_NAME,
        "vault_address": "",
    }


class HyperliquidSystemdCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.private_key = "0x" + ("ab" * 32)
        (self.directory / SYSTEMD_CREDENTIAL_NAME).write_text(
            self.private_key + "\n", encoding="ascii"
        )
        self.environ = {
            "CREDENTIALS_DIRECTORY": str(self.directory),
            "MRV1_HYPERLIQUID_CREDENTIAL_NAME": SYSTEMD_CREDENTIAL_NAME,
            "MRV1_HYPERLIQUID_ACCOUNT_ADDRESS": TRENDATLAS_MASTER_ACCOUNT,
            "MRV1_HYPERLIQUID_AGENT_NAME": TRENDATLAS_AGENT_NAME,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_loads_only_named_systemd_credential(self):
        loaded = load_secret_key(secure_config(), environ=self.environ)
        self.assertEqual(loaded, self.private_key)

    def test_rejects_legacy_environment_inline_and_keystore_sources(self):
        for field, value in (
            ("secret_key_env", "HYPERLIQUID_SECRET_KEY"),
            ("secret_key", self.private_key),
            ("keystore_path", "/tmp/key.json"),
        ):
            config = secure_config()
            config[field] = value
            with self.subTest(field=field), self.assertRaises(SignerCredentialError):
                load_secret_key(config, environ=self.environ)

    def test_missing_systemd_directory_fails_closed(self):
        with self.assertRaisesRegex(SignerCredentialError, "credentials_directory_missing"):
            load_secret_key(secure_config(), environ={})

    def test_private_keys_are_redacted_from_errors(self):
        rendered = redact_sensitive_text(
            f"bad signer {self.private_key} HYPERLIQUID_SECRET_KEY={self.private_key}"
        )
        self.assertNotIn(self.private_key, rendered)
        self.assertNotIn(self.private_key[2:], rendered)
        self.assertGreaterEqual(rendered.count("[REDACTED_PRIVATE_KEY]"), 2)

    def test_derives_distinct_signer_from_credential(self):
        setup = get_account_setup(secure_config(), FakeCrypto(), environ=self.environ)
        self.assertEqual(setup["account_address"], TRENDATLAS_MASTER_ACCOUNT)
        self.assertEqual(setup["signer_address"], FakeWallet.address)
        self.assertTrue(setup["uses_agent_wallet"])
        self.assertNotIn("secret", setup)

    def test_validates_master_role_named_agent_and_expiry(self):
        setup = get_account_setup(secure_config(), FakeCrypto(), environ=self.environ)
        result = validate_account_setup_authorization(
            account_cfg=secure_config(),
            account_setup=setup,
            fetch_user_role=lambda _account: {"role": "user"},
            fetch_extra_agents=lambda _account: [
                {
                    "name": TRENDATLAS_AGENT_NAME,
                    "address": FakeWallet.address,
                    "validUntil": 2_000_000,
                }
            ],
            environ=self.environ,
            now_ms=1_000_000,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["credential_present"])
        self.assertFalse(result["credential_value_exposed"])
        self.assertTrue(result["signer_authorized"])

    def test_wrong_name_or_account_fails_closed(self):
        setup = get_account_setup(secure_config(), FakeCrypto(), environ=self.environ)
        with self.assertRaises(SignerValidationError):
            validate_account_setup_authorization(
                account_cfg=secure_config(),
                account_setup=setup,
                fetch_user_role=lambda _account: {"role": "user"},
                fetch_extra_agents=lambda _account: [
                    {
                        "name": "TrendAtlas",
                        "address": FakeWallet.address,
                        "validUntil": 2_000_000,
                    }
                ],
                environ=self.environ,
                now_ms=1_000_000,
            )
        wrong = secure_config()
        wrong["account_address"] = "0x2222222222222222222222222222222222222222"
        with self.assertRaises(SignerValidationError):
            get_account_setup(wrong, FakeCrypto(), environ=self.environ)

    def test_repo_config_and_unit_forbid_legacy_secret_transport(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "execution/config/hyperliquid_account.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["credential_name"], SYSTEMD_CREDENTIAL_NAME)
        self.assertEqual(config["account_address"], TRENDATLAS_MASTER_ACCOUNT)
        self.assertEqual(config["agent_name"], TRENDATLAS_AGENT_NAME)
        for field in ("secret_key", "secret_key_env", "keystore_path"):
            self.assertNotIn(field, config)
        service = (root / "deploy/systemd/mrv1-production.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("LoadCredentialEncrypted=hyperliquid-agent-private-key:", service)
        self.assertIn("User=trendatlas", service)
        self.assertNotIn("HYPERLIQUID_SECRET_KEY", service)


if __name__ == "__main__":
    unittest.main()
