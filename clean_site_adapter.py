"""Povodny dizajn stranky (app.py) + pravdive data Clean 50/50.

Stranka si zachovava vsetky karty, grafy a texty. Tento modul len nahradi data
stareho modelu (phase67j/68g) datami Clean 50/50 v tom istom formate:
  - verejna publikacia zo servera (Supabase bucket trendatlas-clean-public):
    denny backtest po nakladoch od 2021, drzane vahy, BTC trend, aktualny signal,
  - realny ucet zivo z verejneho Hyperliquid info API (len citanie).
Ziadne kluce, ziadne zapisy.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import streamlit as st

STRATEGY_VERSION = "trendatlas_clean_5050_v1"
BUCKET = "https://figgfdxmlaawoqsgidyx.supabase.co/storage/v1/object/public/trendatlas-clean-public"
HL_INFO = "https://api.hyperliquid.xyz/info"
ACCOUNT = "0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856"  # verejna adresa uctu (aj v execution/config/clean_5050_policy.json)
THRESHOLD = 0.5  # rezim: BTC trend >= 0.5


def _get(url: str, timeout: int = 15) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "TrendAtlas-site"}), timeout=timeout) as r:
        return r.read()


def _post(payload: dict) -> Any:
    req = Request(HL_INFO, data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())


@st.cache_data(ttl=600, show_spinner=False)
def load_clean_public() -> dict[str, Any] | None:
    """Najnovsia overena publikacia (CSV hash musi sediet s JSON)."""
    try:
        version = json.loads(_get(f"{BUCKET}/latest.json"))["version"]
        metrics_body = _get(f"{BUCKET}/{version}/clean5050_metrics.json")
        csv_body = _get(f"{BUCKET}/{version}/clean5050_timeseries.csv", timeout=30)
        signal = json.loads(_get(f"{BUCKET}/{version}/signal.json"))
        metrics = json.loads(metrics_body)
        if hashlib.sha256(csv_body).hexdigest() != metrics.get("timeseries_sha256"):
            return None
        ts = pd.read_csv(io.BytesIO(csv_body))
        if "held_weights" not in ts.columns:
            return None
        return {"version": version, "metrics": metrics, "ts": ts, "signal": signal}
    except Exception:
        return None


def clean_data_is_fresh(clean: dict[str, Any] | None) -> bool:
    """Publikacia je cerstva, ak jej posledny uzavrety den je vcera alebo neskor (UTC)."""
    if not clean:
        return False
    try:
        closed = pd.Timestamp(clean["signal"]["decision_closed_day_utc"])
    except Exception:
        return False
    return closed >= pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)


def _parse(label: Any) -> dict[str, float]:
    text = str(label or "").strip()
    if not text or text == "CASH":
        return {}
    out = {}
    for part in text.split(";"):
        asset, _, weight = part.partition("=")
        if asset and weight:
            out[asset.strip().upper()] = float(weight)
    return out


def _asset_label(weights: dict[str, float]) -> str:
    if not weights:
        return "CASH"
    if set(weights) == {"BTC"}:
        return "BTC"
    btc_first = sorted(weights, key=lambda a: (a != "BTC", a))
    return " + ".join(btc_first)


def _cagr(r: pd.Series) -> float:
    r = pd.to_numeric(r, errors="coerce").fillna(0.0)
    if r.empty:
        return 0.0
    days = len(r)
    return float(((1 + r).prod() ** (365.25 / days) - 1) * 100)


def _metrics(r: pd.Series) -> dict[str, float]:
    r = pd.to_numeric(r, errors="coerce").fillna(0.0)
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    sd = r.std()
    down = r[r < 0].std()
    return {"total_return_pct": float((eq.iloc[-1] - 1) * 100), "cagr_pct": _cagr(r),
            "max_drawdown_pct": float(dd.min() * 100),
            "sharpe": float(r.mean() / sd * math.sqrt(365.25)) if sd > 0 else 0.0,
            "sortino": float(r.mean() / down * math.sqrt(365.25)) if down and down > 0 else 0.0,
            "current_drawdown_pct": float(dd.iloc[-1] * 100)}


def _frame(clean: dict[str, Any]) -> pd.DataFrame:
    ts = clean["ts"].copy()
    ts["ts"] = pd.to_datetime(ts["date"]).dt.normalize()
    ts["held"] = ts["held_weights"].map(_parse)
    ts["target"] = ts["target_weights"].map(_parse)
    ts["held_label"] = ts["held"].map(_asset_label)
    ts["target_label"] = ts["target"].map(_asset_label)
    ts["held_exposure"] = ts["held"].map(lambda w: float(sum(w.values())))
    ts["target_exposure"] = ts["target"].map(lambda w: float(sum(w.values())))
    ts["btc_trend"] = pd.to_numeric(ts["btc_trend"], errors="coerce")
    return ts


def build_production(clean: dict[str, Any], snapshot: dict[str, Any], diagnostics: dict[str, Any]):
    """Vrati (snapshot, timeseries_df, diagnostics) v struktúre povodnej stranky."""
    ts = _frame(clean)
    r = pd.to_numeric(ts["net_return"], errors="coerce").fillna(0.0)
    transition = ts["held_label"].ne(ts["held_label"].shift()) & ts.index.to_series().gt(0)
    cash_day = ts["held_exposure"].le(1e-12)
    btc_day = ts["held_label"].eq("BTC")
    since = lambda day: _cagr(r[ts["ts"] >= pd.Timestamp(day)])

    full = _metrics(r)
    metrics = {"model": STRATEGY_VERSION, **full,
               "since2023_cagr_pct": since("2023-01-01"), "since2025_cagr_pct": since("2025-01-01"),
               "trade_count": int(transition.sum()), "switch_count": int(transition.sum()),
               "cash_days_pct": float(cash_day.mean() * 100), "btc_days_pct": float(btc_day.mean() * 100)}

    last = ts.iloc[-1]
    signal = clean["signal"]
    target_weights = {a.upper(): float(w) for a, w in (signal.get("ciel_vahy") or {}).items() if a.upper() != "CASH" and float(w) > 0}
    target_label = _asset_label(target_weights)
    target_exposure = float(sum(target_weights.values()))
    closed_day = str(signal.get("decision_closed_day_utc") or last["date"])
    trend = float(last["btc_trend"]) if pd.notna(last["btc_trend"]) else None
    regime_on = trend is not None and trend >= THRESHOLD
    changes = ts.loc[transition, ["date", "held_label", "held_exposure"]].tail(12)

    snap = dict(snapshot)
    snap.update({
        "strategy_version": STRATEGY_VERSION, "strategy_id": STRATEGY_VERSION,
        "closed_day": closed_day, "strategy_last_closed_day": closed_day,
        "next_rebalance_date": str((pd.Timestamp(closed_day) + pd.Timedelta(days=2)).date()),
        "candidate_asset": target_label, "selected_asset": target_label,
        "actual_held_asset": target_label, "current_asset": target_label,
        "model_candidate_exposure": target_exposure, "effective_market_exposure": target_exposure,
        "current_exposure": target_exposure, "trend_permission_active": regime_on,
        "trend_score": trend,
        "trend_state": "nad_buy_hranicou" if regime_on and trend > THRESHOLD else "na_buy_hranici" if regime_on else "pod_buy_hranicou",
        "metrics": metrics,
        "execution_intent": {"target_asset": target_label, "target_exposure": target_exposure},
    })
    decision_context = dict(snap.get("decision_context") or {})
    decision_context.update({"current_drawdown_pct": full["current_drawdown_pct"]})
    if target_label != last["held_label"]:
        decision_context.update({"latest_rebalance_date": closed_day,
                                 "latest_rebalance_reason": "rebalance_to_cash" if target_label == "CASH" else "signal_state_change"})
    elif len(changes):
        decision_context.update({"latest_rebalance_date": str(changes.iloc[-1]["date"]),
                                 "latest_rebalance_reason": "rebalance_to_cash" if changes.iloc[-1]["held_label"] == "CASH" else "signal_state_change"})
    snap["decision_context"] = decision_context

    prod = pd.DataFrame({
        "date": ts["date"], "ts": ts["ts"],
        "authorized_return_net": r, "authorized_return_gross": pd.to_numeric(ts["gross_return"], errors="coerce").fillna(0.0),
        "authorized_equity": (1 + r).cumprod(), "asset_transition_day": transition,
        "cash_day": cash_day, "btc_day": btc_day,
        "trend_score": ts["btc_trend"], "buy_threshold": THRESHOLD, "trend_activation_threshold": THRESHOLD,
        "actual_held_asset": ts["held_label"], "candidate_asset": ts["target_label"],
        "held_asset": ts["held_label"], "effective_market_exposure": ts["held_exposure"],
        "trend_permission_active": ts["btc_trend"].ge(THRESHOLD),
    })

    diag = dict(diagnostics)
    diag["current_trade_state"] = {"candidate_asset": target_label, "actual_held_asset": target_label,
                                   "model_candidate_exposure": target_exposure, "trend_permission_active": regime_on}
    diag["current_wait_condition"] = {"code": "already_in_target_state" if regime_on else "trend_confirmation_pending",
                                      "current_values": {"trend_score": trend, "trend_activation_threshold": THRESHOLD},
                                      "target_condition": {"trend_score_min": THRESHOLD}}
    diag["current_pain_points"] = []
    events = []
    for _, row in changes.iloc[::-1].iterrows():
        events.append({"date": row["date"], "held_asset": row["held_label"], "exposure": f"{row['held_exposure']:.2f}x",
                       "regime": "CASH" if row["held_label"] == "CASH" else "BTC" if row["held_label"] == "BTC" else "ALT",
                       "reason_code": "rebalance_to_cash" if row["held_label"] == "CASH" else "rebalance_to_btc" if row["held_label"] == "BTC" else "signal_state_change",
                       "reason_text": "Clean 50/50 signal change"})
    diag["recent_rebalance_events"] = events
    diag["recent_regime_changes"] = events
    return snap, prod, diag


def build_chart(clean: dict[str, Any]) -> pd.DataFrame:
    """Graf 'Modelovy vyvoj vs BTC' v stlpcoch, ktore cita make_production_equity_chart."""
    ts = _frame(clean)
    r = pd.to_numeric(ts["net_return"], errors="coerce").fillna(0.0)
    btc_r = pd.to_numeric(ts["btc_return"], errors="coerce").fillna(0.0)
    model_index = (1 + r).cumprod() * 100
    btc_index = (1 + btc_r).cumprod() * 100
    nan = np.nan
    out = pd.DataFrame({
        "date": ts["date"], "ts": ts["ts"],
        "model_index": model_index, "btc_index": btc_index, "btc_return": btc_r,
        "btc_close": btc_index,
        "model_authorized_exposure_x": ts["held_exposure"], "model_authorized_return_net": r,
        "model_authorized_return_gross": pd.to_numeric(ts["gross_return"], errors="coerce").fillna(0.0),
        "model_transition_cost": pd.to_numeric(ts.get("fees", 0), errors="coerce").fillna(0.0) + pd.to_numeric(ts.get("slippage", 0), errors="coerce").fillna(0.0),
        "model_asset_transition_day": ts["held_label"].ne(ts["held_label"].shift()),
        "live_strategy_index": model_index, "live_strategy_exposure_x": ts["held_exposure"],
        "live_strategy_return_net": r, "live_strategy_vs_btc_return": r - btc_r, "live_strategy_source": "clean_5050_backtest",
        "strategy_execution_index": model_index, "strategy_execution_exposure_x": ts["held_exposure"],
        "strategy_execution_return_net": r, "strategy_execution_vs_btc_return": r - btc_r, "strategy_execution_source": "clean_5050_backtest",
        "real_account_index": nan, "real_account_exposure_x": nan, "real_account_return_net": nan,
        "real_account_vs_btc_return": nan, "real_account_source": "not_derived_from_model",
        "candidate_asset": ts["held_label"], "trend_permission_active": ts["held_exposure"].gt(1e-12),
        "chart_scope": "model",
    })
    # dnesny den drzania (este bez uzavreteho vynosu): aktualny ciel zo signalu
    sig = model_signal_state(clean)
    today = ts["ts"].iloc[-1] + pd.Timedelta(days=1)
    row = out.iloc[[-1]].copy()
    row["ts"] = today
    row["date"] = str(today.date())
    for col in ("btc_return", "model_authorized_return_net", "model_authorized_return_gross", "model_transition_cost",
                "live_strategy_return_net", "live_strategy_vs_btc_return", "strategy_execution_return_net", "strategy_execution_vs_btc_return"):
        row[col] = 0.0
    for col in ("model_authorized_exposure_x", "live_strategy_exposure_x", "strategy_execution_exposure_x"):
        row[col] = sig["exposure_x"]
    row["candidate_asset"] = sig["preferred_asset"]
    row["trend_permission_active"] = sig["exposure_x"] > 1e-12
    row["model_asset_transition_day"] = sig["preferred_asset"] != out["candidate_asset"].iloc[-1]
    return pd.concat([out, row], ignore_index=True)


def model_signal_state(clean: dict[str, Any]) -> dict[str, Any]:
    weights = {a.upper(): float(w) for a, w in (clean["signal"].get("ciel_vahy") or {}).items() if a.upper() != "CASH" and float(w) > 0}
    return {"preferred_asset": _asset_label(weights), "exposure_x": float(sum(weights.values())),
            "not_real_wallet_exposure": True, "label_sk": "Modelový signál",
            "weights": weights}


def model_performance_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    m = snapshot.get("metrics") or {}
    return {"public_average_annual_growth_pct": m.get("cagr_pct"), "since_etf_start_cagr_pct": m.get("since2023_cagr_pct"),
            "since2025_cagr_pct": m.get("since2025_cagr_pct"), "label_sk": "Modelový vývoj vs BTC"}


@st.cache_data(ttl=120, show_spinner=False)
def _account_raw() -> dict[str, Any] | None:
    try:
        return {"perp": _post({"type": "clearinghouseState", "user": ACCOUNT}),
                "spot": _post({"type": "spotClearinghouseState", "user": ACCOUNT}),
                "spot_meta": _post({"type": "spotMetaAndAssetCtxs"}),
                "mids": _post({"type": "allMids"})}
    except Exception:
        return None


def real_account_state(lang: str) -> dict[str, Any] | None:
    """Realny ucet zivo z burzy (verejne info API)."""
    raw = _account_raw()
    if not raw:
        return None
    meta, ctxs = raw["spot_meta"]
    tokens = {t["index"]: t["name"] for t in meta["tokens"]}
    ctx_by_coin = {c.get("coin"): c for c in ctxs}
    pair_price = {}
    for pair in meta["universe"]:
        base = tokens.get(pair["tokens"][0])
        quote = tokens.get(pair["tokens"][1])
        ctx = ctx_by_coin.get(pair["name"]) or {}
        px = float(ctx.get("markPx") or ctx.get("midPx") or 0)
        if base and quote == "USDC" and px > 0:
            pair_price.setdefault(base, px)
    equity, exposure_usd, held = 0.0, 0.0, {}
    for b in raw["spot"].get("balances", []):
        qty = float(b.get("total") or 0)
        if not qty:
            continue
        if b["coin"] == "USDC":
            equity += qty
            continue
        value = qty * pair_price.get(b["coin"], 0.0)
        equity += value
        exposure_usd += abs(value)
        name = {"UBTC": "BTC", "UETH": "ETH"}.get(b["coin"], b["coin"])
        if abs(value) >= 1:
            held[name] = held.get(name, 0.0) + abs(value)
    for p in raw["perp"].get("assetPositions", []):
        pos = p["position"]
        notional = abs(float(pos.get("positionValue") or 0))
        equity += float(pos.get("unrealizedPnl") or 0)
        exposure_usd += notional
        if notional >= 1:
            held[pos["coin"]] = held.get(pos["coin"], 0.0) + notional
    if equity <= 0:
        return None
    exposure = exposure_usd / equity
    in_market = exposure > 0.01
    asset = _asset_label({k: v for k, v in held.items()}) if held else "CASH"
    exposure_text = f"{exposure:.2f}x"
    if lang == "sk":
        state_text = "V trhu" if in_market else "Mimo trhu"
        subtitle = f"{asset} | zostatok {equity:,.2f} $".replace(",", " ") if in_market else f"Hotovosť | zostatok {equity:,.2f} $".replace(",", " ")
    else:
        state_text = "In market" if in_market else "Out of market"
        subtitle = f"{asset} | balance ${equity:,.2f}" if in_market else f"Cash | balance ${equity:,.2f}"
    return {"is_out_of_market": not in_market, "asset": asset if in_market else "CASH", "exposure": exposure,
            "exposure_text": exposure_text, "state_text": state_text,
            "value": f"{asset if in_market else state_text} / {exposure_text}", "subtitle": subtitle,
            "target_asset": asset, "label_sk": "Reálny účet", "equity_usd": equity}
