"""Economic timing, exact reference semantics, and crash-safe dry-run regressions."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from trendatlas_clean import core
from trendatlas_clean.backtest import Costs, metrics, replay
from trendatlas_clean.data import Panel, REFERENCE_SYMBOLS, load
from trendatlas_clean.fetch_data import to_daily
from trendatlas_clean.runner import build_signal, compare_reference, persist


def fixture(rows=650, coins=("BTC", "ETH", "SOL", "TRX", "ZEC", "NEAR")):
    rng = np.random.default_rng(20261018)
    idx = pd.date_range("2024-01-01", periods=rows)
    ret = rng.normal(0.001, 0.025, (rows, len(coins)))
    c = pd.DataFrame(100 * np.exp(ret.cumsum(axis=0)), index=idx, columns=coins)
    q = pd.DataFrame(np.exp(rng.normal(20, 1, (rows, len(coins)))), index=idx, columns=coins)
    return c, q


def reference():
    spec = importlib.util.spec_from_file_location("clean_test_reference", ROOT / "tests/fixtures/clean_5050_reference.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def simple_features(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows))
    cols = ["BTC", "ETH", "SOL"]
    f = {k: pd.DataFrame(1.0, index=idx, columns=cols) for k in ("trend", "score", "liq")}
    f["alive"] = pd.DataFrame(True, index=idx, columns=cols)
    for i, s in enumerate(rows):
        f["score"].iloc[i] = s
    return f


class SignalTests(unittest.TestCase):
    def test_reference_59_has_no_bsv(self):
        self.assertEqual(len(REFERENCE_SYMBOLS), 59)
        self.assertNotIn("BSV", REFERENCE_SYMBOLS)

    def test_feature_equations_exact_reference(self):
        c, q = fixture()
        actual, expected = core.features(c, q), reference().features(c, q)
        for k in actual:
            assert_frame_equal(actual[k], expected[k])

    def test_decisions_exact_reference(self):
        c, q = fixture()
        ref = reference()
        assert_frame_equal(core.decide(core.Params(), core.features(c, q)), ref.decide(ref.Params(), ref.features(c, q)))

    def test_combination_and_no_additional_signal_shift(self):
        c, q = fixture()
        f = core.features(c, q)
        clean = core.decide(core.Params(), f)
        expected = clean * 0.5
        expected["BTC"] += (f["trend"]["BTC"] >= 0.5) * 0.5
        assert_frame_equal(core.target_weights(c, q), expected)

    def test_prefix_invariance(self):
        c, q = fixture()
        full = core.target_weights(c, q)
        for i in (160, 365, 400, 450, 500, 600, 649):
            with self.subTest(i=i):
                assert_frame_equal(core.target_weights(c.iloc[:i + 1], q.iloc[:i + 1]), full.iloc[:i + 1])

    def test_future_mutation_cannot_change_past(self):
        c, q = fixture()
        expected = core.target_weights(c, q)
        c.iloc[500:] *= 100
        q.iloc[500:] *= 0.001
        assert_frame_equal(core.target_weights(c, q).iloc[:500], expected.iloc[:500])

    def test_first_missing_close_immediately_ineligible(self):
        f = simple_features([[0, 2, 1], [0, 3, 1]])
        f["alive"].iloc[1, 1] = False
        f["liq"].iloc[1, 1] = np.nan
        W = core.decide(core.Params(), f)
        self.assertEqual(W.iloc[0]["ETH"], 1)
        self.assertEqual(W.iloc[1]["SOL"], 1)

    def test_ffill_features_does_not_fill_alive(self):
        c, q = fixture()
        c.iloc[500, 1] = np.nan
        f = core.features(c, q)
        self.assertFalse(f["alive"].iloc[500, 1])
        self.assertTrue(pd.isna(f["liq"].iloc[500, 1]))

    def test_hysteresis_is_strictly_greater(self):
        f = simple_features([[0, 2, 1], [0, 2, 2.25], [0, 2, 2.25001]])
        W = core.decide(core.Params(), f)
        self.assertEqual(W.iloc[1]["ETH"], 1)
        self.assertEqual(W.iloc[2]["SOL"], 1)

    def test_negative_trend_or_top10_exit_immediate(self):
        f = simple_features([[0, 2, 1], [0, 3, 1]])
        f["trend"].iloc[1, 1] = 0
        self.assertEqual(core.decide(core.Params(), f).iloc[1]["SOL"], 1)
        f["trend"].iloc[1, 1] = 1
        f["liq"].iloc[1] = [2, 1, 3]
        self.assertEqual(core.decide(core.Params(universe_n=1), f).iloc[1]["SOL"], 1)

    def test_regime_off_cash_and_reset(self):
        f = simple_features([[0, 2, 1], [0, 3, 1], [0, 1, 2]])
        f["trend"].iloc[1, 0] = 0
        W = core.decide(core.Params(), f)
        self.assertEqual(W.iloc[1].sum(), 0)
        self.assertEqual(W.iloc[2]["SOL"], 1)

    def test_btc_preference_applied_once(self):
        W = core.decide(core.Params(), simple_features([[1, 1.2, 0]]))
        self.assertEqual(W.iloc[0]["BTC"], 1)

    def test_tie_break_independent_of_column_order(self):
        f = simple_features([[0, 1, 1]])
        a = core.decide(core.Params(), f)
        b = core.decide(core.Params(), {k: v[v.columns[::-1]] for k, v in f.items()})
        self.assertEqual(a.iloc[0]["ETH"], b.iloc[0]["ETH"])

    def test_minimum_history_365_observed_bars(self):
        c, q = fixture()
        c.iloc[0:20, 1] = np.nan
        f = core.features(c, q)
        self.assertTrue(pd.isna(f["liq"].iloc[383, 1]))
        self.assertTrue(pd.notna(f["liq"].iloc[384, 1]))

    def test_invalid_axes_prices_and_reserved_base_rejected(self):
        c, q = fixture()
        for bad in [c.iloc[::-1], c.rename(columns={"ETH": "BASE"})]:
            with self.assertRaises(ValueError):
                core.features(bad, q)
        c.iloc[3, 0] = 0
        with self.assertRaises(ValueError):
            core.features(c, q)


class AccountingTests(unittest.TestCase):
    def panel(self):
        c, q = fixture(rows=8)
        f = c * 0
        return Panel(c, q, f, f.astype(str).replace("0.0", "OBSERVED"), "test", {})

    def test_gross_identity_and_asset_switch(self):
        p = self.panel()
        W = p.close * 0
        W.loc[W.index[:3], "BTC"] = 0.5
        W.loc[W.index[:3], "SOL"] = 0.5
        W.loc[W.index[3:6], "ETH"] = 1
        result = replay(p, W, Costs(0, 0, 0, 0))
        for i in range(1, len(W)):
            expected = sum(W.iloc[i - 1][c] * (p.close.iloc[i][c] / p.close.iloc[i - 1][c] - 1) for c in W)
            self.assertAlmostEqual(result.iloc[i]["gross_return"], expected, places=14)
        self.assertEqual(result.iloc[0]["gross_return"], 0)

    def test_same_day_loss_cannot_be_erased_by_cash_decision(self):
        p = self.panel()
        p.close.iloc[1, 0] = p.close.iloc[0, 0] * 0.8
        W = p.close * 0
        W.iloc[0, 0] = 1
        result = replay(p, W, Costs(0, 0, 0, 0))
        self.assertAlmostEqual(result.iloc[1]["gross_return"], -0.2)

    def test_rotation_charges_both_sides_and_spot_fee(self):
        p = self.panel()
        W = p.close * 0
        W.iloc[0, 0] = 1
        W.iloc[1, 2] = 1
        r = replay(p, W)
        post_nav = (1 - 9.9 / 10000) / (1 + 7.4 / 10000)
        self.assertAlmostEqual(r.iloc[2]["turnover_notional"], 1 + post_nav)
        self.assertAlmostEqual(r.iloc[2]["fees"], (4.9 + post_nav * 2.4) / 10000)
        self.assertAlmostEqual(r.iloc[2]["slippage"], (1 + post_nav) * 5 / 10000)

    def test_constant_half_weights_charge_price_drift_rebalancing(self):
        p = self.panel()
        p.close[:] = 100
        p.close.iloc[1:, 0] = 200
        W = p.close * 0
        W["BTC"], W["SOL"] = 0.5, 0.5
        r = replay(p, W)
        # After +100% BTC and flat SOL, the holdings are 2/3 and 1/3 before
        # the next half/half rebalance, despite unchanged target weights.
        self.assertGreater(r.iloc[2]["turnover_notional"], 0.3)
        self.assertGreater(r.iloc[2]["fees"], 0)
        self.assertAlmostEqual(r.iloc[2]["post_cost_nav_fraction"], 1 - r.iloc[2]["fees"] - r.iloc[2]["slippage"])

    def test_no_funding_on_spot_btc_eth(self):
        p = self.panel()
        p.funding[:] = 0.1
        W = p.close * 0
        W["BTC"], W["ETH"] = 0.5, 0.5
        self.assertEqual(replay(p, W)["funding_debit"].sum(), 0)

    def test_geometric_cagr_not_average_annual_return(self):
        idx = pd.date_range("2024-01-01", periods=366)
        r = pd.Series(0.0, index=idx)
        r.iloc[0], r.iloc[-1] = 1, -0.5
        ledger = pd.DataFrame({"net_return": r, "invalid_return_or_nav": False, "turnover_notional": 0,
                               "unpriced_execution_proxy": False, "funding_proxy_used": False})
        self.assertAlmostEqual(metrics(ledger)["cagr_pct"], 0)

    def test_price_ffill_stops_after_three_days(self):
        c = pd.DataFrame({"BTC": [100, np.nan, np.nan, np.nan, np.nan, 80]})
        r = core.price_returns(c)
        self.assertEqual(r.iloc[3, 0], 0)
        self.assertTrue(pd.isna(r.iloc[4, 0]))
        self.assertTrue(pd.isna(r.iloc[5, 0]))

    def test_missing_held_return_invalidates_metrics(self):
        p = self.panel()
        p.close.iloc[1:7, 0] = np.nan
        W = p.close.fillna(0) * 0
        W["BTC"] = 1
        r = replay(p, W)
        self.assertEqual(metrics(r)["status"], "INVALID_RETURN_OR_NAV")


class DataAndRuntimeTests(unittest.TestCase):
    def test_millisecond_and_microsecond_daily_archive(self):
        from trendatlas_clean.fetch_data import COLS
        t = int(pd.Timestamp("2026-01-01", tz="UTC").timestamp() * 1000)
        row = [t, 1, 2, 1, 2, 10, t + 1, 20, 1, 1, 1, 0]
        a = to_daily(pd.DataFrame([row], columns=COLS))
        row[0] *= 1000
        b = to_daily(pd.DataFrame([row], columns=COLS))
        assert_frame_equal(a, b)

    def test_conflicting_duplicate_candle_rejected(self):
        from trendatlas_clean.fetch_data import COLS
        row = [1704067200000, 1, 2, 1, 2, 10, 1, 20, 1, 1, 1, 0]
        bad = row.copy()
        bad[4] = 3
        with self.assertRaises(RuntimeError):
            to_daily(pd.DataFrame([row, bad], columns=COLS))

    def test_load_luna_cutoff_and_funding_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ohlcv").mkdir()
            idx = pd.date_range("2022-05-10", periods=8)
            for coin in ["BTC", "LUNA"]:
                pd.DataFrame({"date": idx, "close": 10, "quote_volume": 100}).to_csv(root / "ohlcv" / f"{coin}.csv", index=False)
            p = load(root, "2022-05-17")
            self.assertTrue(pd.isna(p.close.loc["2022-05-14", "LUNA"]))
            self.assertEqual(p.funding_source.loc["2022-05-14", "LUNA"], "DEFAULT_PROXY_0.0003")
            self.assertEqual(p.funding.loc["2022-05-14", "LUNA"], 0.0003)

    def signal(self):
        c, q = fixture()
        day = c.index[-1].date().isoformat()
        return build_signal(c, q, day, input_sha256="a" * 64, now=datetime(2026, 10, 18, tzinfo=timezone.utc))

    def test_signal_close_and_holding_dates_not_shifted(self):
        s = self.signal()
        self.assertEqual(pd.Timestamp(s["drzat_pocas_dna_utc"]) - pd.Timestamp(s["decision_closed_day_utc"]), pd.Timedelta(days=1))
        self.assertEqual(s["orders_sent"], 0)
        self.assertEqual(s["live_order_chain"], "NOT_INVOKED_BY_SIGNAL_PRODUCER")
        self.assertNotIn("BASE", s["ciel_vahy"])
        self.assertAlmostEqual(sum(s["ciel_vahy"].values()), 1)

    def test_no_unclosed_or_stale_btc_signal(self):
        c, q = fixture()
        day = c.index[-1].date().isoformat()
        with self.assertRaises(ValueError):
            build_signal(c, q, day, input_sha256="a", now=datetime.fromisoformat(day).replace(tzinfo=timezone.utc))
        c.iloc[-1, 0] = np.nan
        with self.assertRaises(ValueError):
            build_signal(c, q, day, input_sha256="a")

    def test_restart_is_idempotent_and_backup_integrity_ok(self):
        with tempfile.TemporaryDirectory() as temp:
            p, s = Path(temp), self.signal()
            a = persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            b = persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            self.assertEqual(a["distinct_days"], b["distinct_days"])
            self.assertEqual(b["mandatory_wait_days"], 0)
            db = sqlite3.connect(p / "dry_run.backup.sqlite3")
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            db.close()

    def test_same_day_revision_preserves_original_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            p, s = Path(temp), self.signal()
            persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            old = (p / "signal.json").read_bytes()
            s["ciel_vahy"] = {"BTC": 1.0} if s["ciel_vahy"] != {"BTC": 1.0} else {"CASH": 1.0}
            with self.assertRaisesRegex(ValueError, "DAY_REVISION_DETECTED"):
                persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            self.assertEqual((p / "signal.json").read_bytes(), old)

    def test_same_target_new_provenance_does_not_block_daily_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            p, s = Path(temp), self.signal()
            persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            old = (p / "signal.json").read_bytes()
            s["input_sha256"] = "new source hash, identical decision"
            s["code_sha256"] = "new executor code, identical decision"
            persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            self.assertEqual((p / "signal.json").read_bytes(), old)

    def test_crash_after_sqlite_commit_rematerializes_same_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            p, s = Path(temp), self.signal()
            with patch("trendatlas_clean.runner._atomic_bytes", side_effect=OSError("simulated power loss")):
                with self.assertRaises(OSError):
                    persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            status = persist(p, s, {"status": "NOT_PROVIDED", "matched": None})
            self.assertEqual(status["distinct_days"], 1)
            self.assertEqual(json.loads((p / "signal.json").read_text())["ciel_vahy"], s["ciel_vahy"])

    def test_reference_day_mismatch_does_not_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "reference.json"
            p.write_text(json.dumps({"decision_closed_day_utc": "2000-01-01", "ciel_vahy": {"CASH": 1}}))
            self.assertFalse(compare_reference(self.signal(), p)["matched"])

    def test_funding_btc_proxy_is_not_observed_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ohlcv").mkdir()
            (root / "funding").mkdir()
            for coin in ["BTC", "SOL"]:
                pd.DataFrame({"date": ["2026-01-01"], "close": [100], "quote_volume": [1000]}).to_csv(root / "ohlcv" / f"{coin}.csv", index=False)
            pd.DataFrame({"date": ["2026-01-01"], "funding_daily": [0.001]}).to_csv(root / "funding/BTC.csv", index=False)
            p = load(root, "2026-01-01")
            self.assertEqual(p.funding.loc["2026-01-01", "SOL"], 0.001)
            self.assertEqual(p.funding_source.loc["2026-01-01", "SOL"], "BTC_PROXY")
            self.assertEqual(p.funding_source.loc["2026-01-01", "BTC"], "OBSERVED")

    def test_duplicate_dates_rejected_in_input_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ohlcv").mkdir()
            pd.DataFrame({"date": ["2026-01-01"] * 2, "close": [100, 101], "quote_volume": [10, 11]}).to_csv(root / "ohlcv/BTC.csv", index=False)
            with self.assertRaisesRegex(ValueError, "Duplicate dates"):
                load(root, "2026-01-01")


class ShutdownTests(unittest.TestCase):
    @staticmethod
    def module():
        spec = importlib.util.spec_from_file_location("clean_shutdown_test", ROOT / "scripts/production/disable_phase68g.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def fake_root(self, temp):
        root = Path(temp)
        p = root / "execution/config/execution_mode.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"mode": "live", "trading_enabled": True, "kill_switch": False, "dry_run_enabled": False}))
        return root, p

    def test_shutdown_dry_run_never_changes_flags_or_calls_systemd(self):
        with tempfile.TemporaryDirectory() as temp:
            root, p = self.fake_root(temp)
            before = p.read_bytes()
            report = self.module().disable(root, systemctl=lambda *a: self.fail("systemctl during dry-run"))
            self.assertFalse(report["applied"])
            self.assertEqual(before, p.read_bytes())

    def test_shutdown_has_no_service_start_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root, p = self.fake_root(temp)
            original = p.read_bytes()
            calls = []
            def systemctl(*args):
                calls.append(args)
                text = str(root) + "/scripts/execution/run_trendatlas_production.py" if args[0] == "show" else "inactive" if args[0] == "is-active" else "disabled" if args[0] == "is-enabled" else ""
                return subprocess.CompletedProcess(args, 0, text, "")
            result = self.module().disable(root, apply=True, systemctl=systemctl)
            self.assertTrue(result["verified_disabled"])
            self.assertTrue(json.loads(p.read_text())["kill_switch"])
            self.assertFalse(any("start" in args for args in calls))
            self.assertEqual(p.with_name("execution_mode.pre_clean_shutdown.json").read_bytes(), original)
            self.assertEqual(result["orders_sent"], 0)

    def test_wrong_runtime_root_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root, p = self.fake_root(temp)
            original = p.read_bytes()
            with self.assertRaisesRegex(ValueError, "ExecStart"):
                self.module().disable(root, apply=True, systemctl=lambda *a: subprocess.CompletedProcess(a, 0, "/different/runtime", ""))
            self.assertEqual(p.read_bytes(), original)

    def test_removed_seven_day_wait_not_reintroduced_in_contract(self):
        c = json.loads((ROOT / "source_of_truth/clean_5050_contract.json").read_text())
        self.assertFalse(c["dry_run"]["required"])
        self.assertEqual(c["dry_run"]["minimum_elapsed_days"], 0)


if __name__ == "__main__":
    unittest.main()
