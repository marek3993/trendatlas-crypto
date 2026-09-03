import unittest

from scripts.execution.build_hyperliquid_real_performance_ledger import build_ledger


ADDRESS = "0x0000000000000000000000000000000000000001"


def valuation(day: str, equity: float) -> dict:
    return {
        "valuation_id": f"seed:{day}", "timestamp_utc": f"{day}T00:00:00Z",
        "effective_day": day, "equity_usd": equity, "free_collateral_usd": equity,
        "margin_used_usd": 0.0, "source": "test",
    }


def snapshot(day: str, equity: float, *, fills=None, funding=None, non_funding=None) -> dict:
    return {
        "account_address": ADDRESS, "as_of_utc": f"{day}T23:00:00Z",
        "summary": {"account_equity_usd": equity, "available_balance_usd": equity, "margin_summary": {}},
        "raw": {
            "clearinghouseState": {"assetPositions": []}, "userFills": [], "userFillsByTime": fills or [],
            "userFunding": funding or [], "userNonFundingLedgerUpdates": non_funding or [], "portfolio": [],
        },
    }


def ms(day: str) -> int:
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(f"{day}T12:00:00+00:00").timestamp() * 1000)


class TestHyperliquidRealPerformanceLedger(unittest.TestCase):
    def build(self, end_equity: float, *, fills=None, funding=None, non_funding=None):
        return build_ledger(
            snapshot("2026-09-02", end_equity, fills=fills, funding=funding, non_funding=non_funding),
            {"events": [], "equity_valuations": [valuation("2026-09-01", 100.0)]},
        )

    def test_deposit_is_not_profit(self):
        ledger = self.build(200.0, non_funding=[{"time": ms("2026-09-02"), "hash": "deposit", "delta": {"type": "deposit", "usdc": "100"}}])
        self.assertEqual(ledger["current"]["daily_net_pnl_usd"], 0.0)
        self.assertEqual(ledger["current"]["deposits_usd"], 100.0)

    def test_profit_without_cash_flow(self):
        ledger = self.build(110.0)
        self.assertEqual(ledger["current"]["daily_net_pnl_usd"], 10.0)

    def test_deposit_plus_profit(self):
        ledger = self.build(215.0, non_funding=[{"time": ms("2026-09-02"), "hash": "deposit", "delta": {"type": "deposit", "usdc": "100"}}])
        self.assertEqual(ledger["current"]["daily_net_pnl_usd"], 15.0)

    def test_withdrawal_is_not_loss(self):
        ledger = build_ledger(
            snapshot("2026-09-02", 150.0, non_funding=[{"time": ms("2026-09-02"), "hash": "withdraw", "delta": {"type": "withdraw", "usdc": "50"}}]),
            {"events": [], "equity_valuations": [valuation("2026-09-01", 200.0)]},
        )
        self.assertEqual(ledger["current"]["daily_net_pnl_usd"], 0.0)
        self.assertEqual(ledger["current"]["withdrawals_usd"], 50.0)

    def test_negative_exchange_withdrawal_is_normalized_to_positive_external_amount(self):
        ledger = build_ledger(
            snapshot("2026-09-02", 150.0, non_funding=[{"time": ms("2026-09-02"), "hash": "withdraw-negative", "delta": {"type": "withdraw", "usdc": "-50"}}]),
            {"events": [], "equity_valuations": [valuation("2026-09-01", 200.0)]},
        )
        self.assertEqual(ledger["current"]["withdrawals_usd"], 50.0)
        self.assertEqual(ledger["current"]["daily_net_pnl_usd"], 0.0)

    def test_cash_flow_return_is_unavailable_without_intraday_valuation(self):
        ledger = self.build(200.0, non_funding=[{"time": ms("2026-09-02"), "hash": "deposit", "delta": {"type": "deposit", "usdc": "100"}}])
        self.assertFalse(ledger["windows"]["today"]["available"])
        self.assertEqual(ledger["windows"]["30d"]["reason"], "insufficient_live_history")

    def test_fees_and_funding_are_independent_reconciliation_components(self):
        ledger = self.build(109.4, fills=[{"time": ms("2026-09-02"), "tid": 1, "closedPnl": "10", "fee": "0.5"}], funding=[{"time": ms("2026-09-02"), "hash": "funding", "coin": "BTC", "usdc": "-0.1"}])
        self.assertEqual(ledger["current"]["daily_net_pnl_usd"], 9.4)
        self.assertEqual(ledger["current"]["exchange_event_net_pnl_usd"], 9.4)
        self.assertEqual(ledger["current"]["equity_event_reconciliation_delta_usd"], 0.0)

    def test_duplicate_ingestion_is_idempotent(self):
        incoming = [{"time": ms("2026-09-02"), "hash": "deposit", "delta": {"type": "deposit", "usdc": "100"}}]
        first = self.build(200.0, non_funding=incoming)
        second = build_ledger(snapshot("2026-09-02", 200.0, non_funding=incoming), first)
        self.assertEqual(len(first["events"]), len(second["events"]))
        self.assertEqual(second["current"]["deposits_usd"], 100.0)

    def test_model_fields_cannot_enter_real_performance_ledger(self):
        ledger = self.build(110.0)
        serialized = str(ledger)
        self.assertNotIn("rolling_return_30d", serialized)
        self.assertNotIn("rolling_return_90d", serialized)


if __name__ == "__main__":
    unittest.main()
