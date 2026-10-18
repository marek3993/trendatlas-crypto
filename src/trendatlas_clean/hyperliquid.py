"""Hyperliquid metadata/read-back and explicitly armed, credential-only transport.

No retry of a signed HTTP request. Only /info is used until arm() is called.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from .portfolio import Account, Catalog, Market, Position, number
from .journal import ConfirmedRejection, NoSubmission

API = "https://api.hyperliquid.xyz"
CREDENTIAL = "hyperliquid-agent-private-key"


def post(path: str, payload: dict):
    request = Request(API + path, json.dumps(payload, allow_nan=False).encode(),
                      {"Content-Type": "application/json", "User-Agent": "TrendAtlas-Clean/1.0"})
    with urlopen(request, timeout=25) as response:
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("EXCHANGE_RESPONSE_TOO_LARGE")
    return json.loads(body)


def catalog_from(spot: list, perps: list[tuple[str, int, list]]) -> Catalog:
    markets, routes = {}, {}
    meta, contexts = spot
    tokens = {int(t["index"]): t for t in meta["tokens"]}
    ctx = {c["coin"]: c for c in contexts}
    spot_choices = {}
    for item in meta["universe"]:
        base, quote = (tokens[int(i)] for i in item["tokens"])
        if quote["name"] != "USDC" or item["name"] not in ctx:
            continue
        raw = ctx[item["name"]].get("markPx") or ctx[item["name"]].get("midPx")
        if raw is None or number(raw) <= 0:
            continue
        logical = {"UBTC": "BTC", "UETH": "ETH"}.get(base["name"], base["name"])
        key = "spot:" + item["name"]
        m = Market(key, logical, "spot", item["name"], 10000 + int(item["index"]),
                   int(base["szDecimals"]), number(raw), token_index=int(base["index"]))
        markets[key] = m
        spot_choices.setdefault(base["name"], []).append(key)
    # Identity is from token name + USDC quote, not a hardcoded numeric market ID.
    for logical, token in (("BTC", "UBTC"), ("ETH", "UETH")):
        choices = spot_choices.get(token, [])
        if len(choices) == 1:
            routes[logical] = choices[0]
    for dex, offset, response in perps:
        pm, pc = response
        for i, item in enumerate(pm["universe"]):
            context = pc[i]
            raw = context.get("markPx")
            if raw is None or number(raw) <= 0:
                continue
            coin = item["name"]
            key = "perp:" + coin
            m = Market(key, coin, "perp", coin, offset + i, int(item["szDecimals"]),
                       number(raw), entry_available=not item.get("isDelisted", False))
            markets[key] = m
            # Main DEX exact identity only. No LUNA/LUNC or scaled-token guessing.
            if not dex and coin not in {"BTC", "ETH", "BASE"} and m.entry_available:
                routes[coin] = key
    return Catalog(markets, routes)


def account_from(spot: dict, states: list[dict], abstraction: str, catalog: Catalog,
                 open_orders: list[dict]) -> Account:
    positions, blockers = {}, []
    by_token = {m.token_index: m for m in catalog.markets.values() if m.venue == "spot"}
    equity, cash = 0.0, 0.0
    for balance in spot.get("balances", []):
        qty, held = number(balance["total"]), number(balance.get("hold", 0))
        if qty == 0:
            continue
        if balance["coin"] == "USDC":
            equity += qty
            cash += max(0, qty - held)
        elif int(balance["token"]) in by_token:
            m = by_token[int(balance["token"])]
            positions[m.key] = Position(m.key, qty, m.mark, m.logical, m.venue)
            equity += qty * m.mark
        else:
            blockers.append("UNVALUED_SPOT_BALANCE:" + balance["coin"])
    for state in states:
        for ap in state.get("assetPositions", []):
            p = ap["position"]
            qty = number(p["szi"])
            if not qty:
                continue
            key = "perp:" + p["coin"]
            m = catalog.markets.get(key)
            if m is None:
                # Keep the unknown position visible so planning blocks ENTRY,
                # while allowing independent known-position EXITs.
                mark = abs(number(p["positionValue"]) / qty)
                blockers.append("UNRESOLVED_PERP_MARKET:" + p["coin"])
            else:
                mark = abs(number(p["positionValue"]) / qty)
            positions[key] = Position(key, qty, mark, p["coin"], "perp", int(p["leverage"]["value"]))
    if abstraction in {"disabled", "default"}:
        equity += sum(number(s["marginSummary"]["accountValue"]) for s in states)
        margin_free = sum(max(0, number(s.get("withdrawable", 0))) for s in states)
    elif abstraction == "unifiedAccount":
        # Official account-abstraction docs: all balances/holds are in spot state;
        # individual perp accountValue values must NOT be added a second time.
        margin_free = cash
    else:
        # Portfolio-margin can automatically borrow. This implementation never
        # opts the account into that mode or silently treats loans as cash.
        margin_free = cash
        blockers.append("UNSUPPORTED_ABSTRACTION_FOR_ENTRY:" + abstraction)
    return Account(equity, positions, cash, margin_free, abstraction, open_orders, blockers,
                   datetime.now(timezone.utc).isoformat())


def normalize_status(response: dict) -> dict:
    if response.get("status") == "unknownOid":
        return {"state": "NOT_FOUND"}
    if response.get("status") != "order":
        raise ValueError("UNRECOGNIZED_ORDER_STATUS")
    detail = response["order"]
    raw, order = detail["status"], detail["order"]
    if raw == "filled":
        state = "FILLED"
    elif raw == "canceled" or raw.endswith("Canceled") or raw == "scheduledCancel":
        state = "CANCELED"
    elif raw == "rejected" or raw.endswith("Rejected"):
        state = "REJECTED"
    elif raw == "open":
        state = "OPEN"
    else:
        raise ValueError("UNRECOGNIZED_ORDER_STATUS:" + raw)
    return {"state": state, "exchange_status": raw, "remaining": number(order["sz"]), "oid": order["oid"]}


class Broker:
    def __init__(self, account: str, journal, config_path: Path, *, transport=post, clock=time.time):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", account):
            raise ValueError("INVALID_MASTER_ACCOUNT")
        self.account, self.journal, self.config_path = account, journal, config_path
        self.transport, self.clock = transport, clock
        self.wallet = None
        self._exchange_attempts = 0
        self._catalog, self._loaded, self._marks_loaded = None, 0, 0
        self.dexes = [""]

    def info(self, kind: str, **fields):
        return self.transport("/info", {"type": kind, **fields})

    def catalog(self) -> Catalog:
        if self._catalog is None or self.clock() - self._loaded > 300:
            dexes = self.info("perpDexs")
            self.dexes = [""] + [d["name"] for d in dexes[1:] if d]
            def read(pair):
                i, dex = pair
                return (dex, 0 if i == 0 else 110000 + (i - 1) * 10000,
                        self.info("metaAndAssetCtxs", dex=dex))
            with ThreadPoolExecutor(max_workers=4) as pool:
                perps = list(pool.map(read, enumerate(self.dexes)))
            self._catalog = catalog_from(self.info("spotMetaAndAssetCtxs"), perps)
            self._loaded = self.clock()
        if self.clock() - self._marks_loaded > 2:
            mids = self.info("allMids")
            self._catalog.markets = {key: replace(m, mark=number(mids[m.coin]))
                                     if m.coin in mids and number(mids[m.coin]) > 0 else m
                                     for key, m in self._catalog.markets.items()}
            self._marks_loaded = self.clock()
        return self._catalog

    def snapshot(self) -> Account:
        catalog = self.catalog()
        def read(dex):
            return (self.info("clearinghouseState", user=self.account, dex=dex),
                    self.info("openOrders", user=self.account, dex=dex))
        with ThreadPoolExecutor(max_workers=4) as pool:
            readbacks = list(pool.map(read, self.dexes))
        states = [s for s, _ in readbacks]
        orders = [o for _, orders in readbacks for o in orders]
        abstraction = self.info("userAbstraction", user=self.account)
        return account_from(self.info("spotClearinghouseState", user=self.account), states, abstraction, catalog, orders)

    def quote(self, market: Market) -> tuple[float, float]:
        book = self.info("l2Book", coin=market.coin)
        return number(book["levels"][0][0]["px"]), number(book["levels"][1][0]["px"])

    def order_status(self, cloid: str) -> dict:
        return normalize_status(self.info("orderStatus", user=self.account, oid=cloid))

    def arm(self, agent_name: str) -> dict:
        # No inline key, private-key environment variable, CLI secret or plaintext
        # checkout file. systemd supplies the existing encrypted named credential.
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if not directory:
            raise ValueError("SYSTEMD_CREDENTIAL_REQUIRED")
        from eth_account import Account as EthAccount
        self.wallet = EthAccount.from_key((Path(directory) / CREDENTIAL).read_text().strip())
        agents = self.info("extraAgents", user=self.account)
        authorized = [a for a in agents if a.get("name") == agent_name
                      and a["address"].lower() == self.wallet.address.lower()
                      and int(a["validUntil"]) > self.clock() * 1000 + 60000]
        if len(authorized) != 1 or self.wallet.address.lower() == self.account.lower():
            self.wallet = None
            raise ValueError("NAMED_AGENT_NOT_AUTHORIZED_OR_EXPIRED")
        return {"signer_verified": True, "agent_name": agent_name, "orders_sent": 0}

    def _action(self, action: dict):
        config = json.loads(self.config_path.read_text())
        if self.wallet is None or config.get("kill_switch") is not False or config.get("trading_enabled") is not True:
            raise ValueError("CLEAN_TRADING_NOT_ARMED")
        if config["account"].lower() != self.account.lower():
            raise ValueError("ACCOUNT_CHANGED_DURING_RUN")
        from hyperliquid.utils.signing import sign_l1_action
        nonce = self.journal.nonce(int(self.clock() * 1000))
        expires = int(self.clock() * 1000) + 120000
        signature = sign_l1_action(self.wallet, action, None, nonce, expires, True)
        self._exchange_attempts += 1
        result = self.transport("/exchange", {"action": action, "nonce": nonce,
                                "signature": signature, "vaultAddress": None, "expiresAfter": expires})
        if result.get("status") != "ok":
            raise ConfirmedRejection("EXCHANGE_ACTION_REJECTED")
        return result

    def place(self, payload: dict, cloid: str) -> dict:
        before = self._exchange_attempts
        try:
            return self._place(payload, cloid)
        except Exception as exc:
            if self._exchange_attempts == before:
                raise NoSubmission("PRE_SUBMIT_FAILURE:" + type(exc).__name__) from exc
            raise

    def _place(self, payload: dict, cloid: str) -> dict:
        from hyperliquid.utils.signing import order_request_to_order_wire, order_wires_to_order_action
        from hyperliquid.utils.types import Cloid
        market = self.catalog().markets[payload["market_key"]]
        if not payload["reduce_only"] and market.venue == "perp":
            # Recheck actual account capacity; no borrowing or transfers.
            account = self.snapshot()
            required = payload["quantity"] * payload["price"] * 1.001
            if account.entry_blockers or account.open_orders or required > account.perp_margin_free:
                return {"state": "REJECTED", "reason": "INSUFFICIENT_UNBORROWED_PERP_COLLATERAL_OR_OPEN_ORDERS", "request_sent": False, "remaining": payload["quantity"]}
        if market.venue == "spot" and payload["side"] == "BUY":
            account = self.snapshot()
            if account.entry_blockers or account.open_orders or payload["quantity"] * payload["price"] * 1.001 > account.spot_cash_free:
                return {"state": "REJECTED", "reason": "INSUFFICIENT_UNBORROWED_SPOT_CASH_OR_OPEN_ORDERS", "request_sent": False, "remaining": payload["quantity"]}
        request = {"coin": market.coin, "is_buy": payload["side"] == "BUY", "sz": payload["quantity"],
                   "limit_px": payload["price"], "order_type": {"limit": {"tif": payload["tif"]}},
                   "reduce_only": payload["reduce_only"], "cloid": Cloid.from_str(cloid)}
        wire = order_request_to_order_wire(request, market.asset_id)
        result = self._action(order_wires_to_order_action([wire]))
        s = result["response"]["data"]["statuses"][0]
        if "error" in s:
            return {"state": "REJECTED", "reason": s["error"], "remaining": payload["quantity"]}
        if "filled" in s:
            return {"state": "FILLED", "remaining": 0, "oid": s["filled"]["oid"]}
        if "resting" in s:
            return {"state": "OPEN", "remaining": payload["quantity"], "oid": s["resting"]["oid"]}
        raise ValueError("UNKNOWN_SUBMIT_RESPONSE")

    def cancel(self, key: str, cloid: str):
        return self._action({"type": "cancelByCloid", "cancels": [
            {"asset": self.catalog().markets[key].asset_id, "cloid": cloid}]})

    def set_leverage(self, market: Market, value: int):
        if value != 1 or market.venue != "perp":
            raise ValueError("ONLY_ONE_X_PERP_SUPPORTED")
        return self._action({"type": "updateLeverage", "asset": market.asset_id, "isCross": True, "leverage": 1})
