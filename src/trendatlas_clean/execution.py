"""Portfolio state machine. Tests inject a broker; this module has no HTTP/signing."""
from __future__ import annotations

from dataclasses import asdict
import json
import time

from .journal import Journal, ConfirmedRejection, NoSubmission, TERMINAL_ORDERS, target_binding
from .portfolio import Catalog, Policy, Trade, order_price, plan, reconcile, size_down


class ReconcileRequired(RuntimeError):
    pass


class Engine:
    def __init__(self, broker, journal: Journal, policy: Policy = Policy(), *, clock=time.time, sleep=time.sleep):
        self.broker, self.journal, self.policy = broker, journal, policy
        self.clock, self.sleep = clock, sleep
        self.sent = 0
        self.events = []

    def _observe(self, row: dict) -> dict:
        status = self.broker.order_status(row["cloid"])
        state = status["state"]
        if state == "NOT_FOUND":
            if row["state"] == "PREPARED":
                return status
            # A lost submit response is not evidence that an order was rejected.
            raise ReconcileRequired(f"SUBMISSION_UNCERTAIN:{row['cloid']}")
        self.journal.update(row["cloid"], state, status)
        return status

    def _wait_terminal(self, row: dict, *, recover: bool = False) -> dict:
        while True:
            status = self._observe(self.journal.order(row["cloid"]))
            if status["state"] in TERMINAL_ORDERS:
                return status
            if status["state"] == "NOT_FOUND":
                return status
            if row["tif"] == "Ioc" or self.clock() >= row["deadline"]:
                self.broker.cancel(row["market_key"], row["cloid"])
                status = self._observe(self.journal.order(row["cloid"]))
                if status["state"] not in TERMINAL_ORDERS:
                    raise ReconcileRequired(f"CANCEL_NOT_CONFIRMED:{row['cloid']}")
                return status
            self.sleep(min(self.policy.poll_seconds, max(0, row["deadline"] - self.clock())))

    def recover_pending(self) -> list[str]:
        unresolved = []
        for row in self.journal.pending():
            try:
                status = self._wait_terminal(row, recover=True)
                if status["state"] == "NOT_FOUND" and row["state"] == "PREPARED":
                    # PREPARED is durably before the submitting boundary: no request was attempted.
                    self.journal.update(row["cloid"], "CANCELED", {"reason": "UNSUBMITTED_RESERVATION"})
            except Exception as exc:
                unresolved.append(row["market_key"])
                self.events.append({"phase": row["phase"], "market_key": row["market_key"],
                                    "reason": str(exc) if isinstance(exc, ReconcileRequired) else type(exc).__name__})
        return unresolved

    def _submit(self, day: str, binding: str, trade: Trade, catalog: Catalog, tif: str, quantity: float) -> dict:
        market = catalog.markets[trade.market_key]
        bid, ask = self.broker.quote(market)
        if bid <= 0 or ask <= 0 or bid > ask:
            raise ValueError("INVALID_ORDER_BOOK")
        buy = trade.side == "BUY"
        if tif == "Alo":
            px = order_price(bid if buy else ask, market, round_up=not buy)
        else:
            raw = ask * (1 + self.policy.max_slippage_bps / 10000) if buy else bid * (1 - self.policy.max_slippage_bps / 10000)
            px = order_price(raw, market, round_up=not buy)
        if px * quantity < self.policy.minimum_notional_usd and not trade.reduce_only:
            return {"state": "REJECTED", "reason": "BELOW_MIN_NOTIONAL", "remaining": quantity}
        payload = {"market_key": market.key, "asset_id": market.asset_id, "side": trade.side,
                   "quantity": quantity, "price": px, "reduce_only": trade.reduce_only, "tif": tif}
        deadline = self.clock() + (self.policy.maker_wait_seconds if tif == "Alo" else self.policy.poll_seconds)
        row = self.journal.reserve(day, binding, trade.phase, market.key, tif, payload, deadline)
        # The durable SUBMITTING record precedes the network request.
        self.journal.update(row["cloid"], "SUBMITTING")
        self.sent += 1  # attempted submission; a lost response may still be filled
        try:
            status = self.broker.place(payload, row["cloid"])
        except ConfirmedRejection:
            status = {"state": "REJECTED", "request_sent": True, "reason": "EXCHANGE_ACTION_REJECTED", "remaining": quantity}
            self.journal.update(row["cloid"], "REJECTED", status)
            return status
        except NoSubmission as exc:
            self.sent -= 1
            status = {"state": "REJECTED", "request_sent": False, "reason": str(exc), "remaining": quantity}
            self.journal.update(row["cloid"], "REJECTED", status)
            return status
        except Exception as exc:
            self.journal.update(row["cloid"], "UNKNOWN", {"reason": type(exc).__name__})
            # Query by the original CLOID, never resend the original request.
            return self._wait_terminal(self.journal.order(row["cloid"]))
        if status.get("request_sent") is False:
            self.sent -= 1
        self.journal.update(row["cloid"], status["state"], status)
        if status["state"] in TERMINAL_ORDERS:
            return status
        return self._wait_terminal(self.journal.order(row["cloid"]))

    def execute_trade(self, day: str, binding: str, trade: Trade, catalog: Catalog):
        market = catalog.markets[trade.market_key]
        if trade.phase == "ENTRY" and market.venue == "perp":
            self.broker.set_leverage(market, 1)
        status = self._submit(day, binding, trade, catalog, "Alo", trade.quantity)
        if status["state"] not in TERMINAL_ORDERS:
            raise ReconcileRequired("MAKER_OUTCOME_UNCERTAIN")
        # Recompute the residual from actual balances after confirmed maker cancel/fill.
        account = self.broker.snapshot()
        pos = account.positions.get(market.key)
        current = pos.quantity if pos else 0.0
        if trade.phase == "EXIT":
            residual = max(0, current - trade.target_quantity) if trade.side == "SELL" else max(0, -current)
        else:
            residual = max(0, trade.target_quantity - current)
        residual = min(trade.quantity, size_down(residual, market.size_decimals))
        if residual > 0 and (trade.reduce_only or residual * market.mark >= self.policy.minimum_notional_usd):
            self._submit(day, binding, trade, catalog, "Ioc", residual)

    def execute(self, signal: dict) -> dict:
        weights = signal["ciel_vahy"]
        day, binding = signal["decision_closed_day_utc"], target_binding(signal)
        run = self.journal.begin(day, binding, signal)
        catalog = self.broker.catalog()
        if run["state"] == "COMPLETE":
            account = self.broker.snapshot()
            return {"strategy_id": signal["strategy_id"], "status": "ALREADY_COMPLETED", "orders_sent_this_invocation": 0, "account_aligned": reconcile(weights, account, catalog, self.policy)["aligned"],
                    "decision_closed_day_utc": day, "readback": reconcile(weights, account, catalog, self.policy)}
        unresolved = self.recover_pending()
        for _ in range(self.policy.max_rebalance_rounds):
            catalog = self.broker.catalog()
            account = self.broker.snapshot()
            p = plan(weights, account, catalog, self.policy)
            executable_exits = [t for t in p.exits if t.market_key not in unresolved]
            for trade in executable_exits:
                try:
                    self.execute_trade(day, binding, trade, catalog)
                except Exception as exc:
                    self.events.append({"phase": "EXIT", "market_key": trade.market_key,
                                        "reason": str(exc) if isinstance(exc, ReconcileRequired) else type(exc).__name__})
                    unresolved.append(trade.market_key)
            # No ENTRY while a needed EXIT or an uncertain prior order remains.
            account = self.broker.snapshot()
            p = plan(weights, account, catalog, self.policy)
            if unresolved or p.exits or p.exit_blockers:
                if executable_exits and not unresolved and p.exits:
                    continue
                break
            external = [o for o in account.open_orders if o.get("cloid") not in self.journal.owned_cloids()]
            if external:
                self.events.append({"phase": "ENTRY", "reason": "EXTERNAL_OPEN_ORDERS", "count": len(external)})
                break
            # Entries are independent: an unavailable target never prevents closing an old coin.
            for trade in p.entries:
                if p.entry_blockers and any(not x.startswith("MARKET_UNAVAILABLE:") for x in p.entry_blockers):
                    break
                try:
                    # Account and target sizing must be refreshed after every preceding fill.
                    fresh = plan(weights, self.broker.snapshot(), self.broker.catalog(), self.policy)
                    candidate = next((t for t in fresh.entries if t.market_key == trade.market_key), None)
                    if candidate:
                        self.execute_trade(day, binding, candidate, self.broker.catalog())
                except Exception as exc:
                    self.events.append({"phase": "ENTRY", "market_key": trade.market_key,
                                        "reason": str(exc) if isinstance(exc, ReconcileRequired) else type(exc).__name__})
                    if isinstance(exc, ReconcileRequired):
                        unresolved.append(trade.market_key)
                        break
            if unresolved:
                break
            # Existing perp positions also need their margin setting changed to 1x,
            # even when their notional already matches the target.
            account = self.broker.snapshot()
            fresh_plan = plan(weights, account, catalog, self.policy)
            for key, pos in account.positions.items():
                if key in fresh_plan.targets and pos.venue == "perp" and pos.quantity and pos.leverage != 1:
                    try:
                        self.broker.set_leverage(catalog.markets[key], 1)
                    except Exception as exc:
                        self.events.append({"phase": "LEVERAGE", "market_key": key, "reason": type(exc).__name__})
            check = reconcile(weights, self.broker.snapshot(), self.broker.catalog(), self.policy)
            if check["aligned"]:
                break
        account = self.broker.snapshot()
        readback = reconcile(weights, account, self.broker.catalog(), self.policy)
        unknown_orders = self.journal.pending()
        aligned = readback["aligned"] and not unknown_orders and not account.open_orders
        status = "FILLED_AND_ALIGNED" if aligned and self.sent else "NO_ACTION_ALIGNED" if aligned else "RECONCILE_REQUIRED"
        receipt = {"strategy_id": signal["strategy_id"], "decision_closed_day_utc": day, "status": status,
                   "account_aligned": aligned, "orders_sent_this_invocation": self.sent,
                   "events": self.events, "readback": readback,
                   "pending_cloids": [r["cloid"] for r in unknown_orders], "completed_at_unix": self.clock()}
        self.journal.finish(day, "COMPLETE" if aligned else "RETRY_REQUIRED", receipt)
        self.journal.backup()
        return receipt
