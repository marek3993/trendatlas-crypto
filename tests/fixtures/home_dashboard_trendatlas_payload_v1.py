# Sanitized kiosk function fixture; no authentication defaults or secrets.
from datetime import datetime, timezone
from http import HTTPStatus

def trendatlas_payload():
    snapshot, snapshot_error = read_json_file(CONFIG["STRATEGY_SNAPSHOT_PATH"])
    health, health_error = read_json_file(CONFIG["DATA_HEALTH_PATH"])
    diagnostics, diagnostics_error = read_json_file(CONFIG["STRATEGY_DIAGNOSTICS_PATH"])
    account_snapshot, account_error = read_json_file(CONFIG["ACCOUNT_SNAPSHOT_PATH"])
    runtime_snapshot, runtime_error = read_json_file(CONFIG["APP_RUNTIME_SNAPSHOT_PATH"])
    dashboard_public_status, dashboard_public_error = read_json_file(CONFIG["DASHBOARD_PUBLIC_STATUS_PATH"])
    execution_intent_payload, execution_intent_error = read_json_file(CONFIG["EXECUTION_INTENT_PATH"])
    real_order_gate_payload, real_order_gate_error = read_json_file(CONFIG["REAL_ORDER_GATE_PATH"])
    rows, rows_error = cached_file(CONFIG["DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH"], load_timeseries)
    rows = rows or []
    latest = rows[-1] if rows else {}
    previous = rows[-2] if len(rows) > 1 else {}
    latest_date = row_date(latest)

    def row_value(row, *keys, default=None):
        for key in keys:
            value = safe_float(row.get(key))
            if value is not None:
                return value
        return default

    latest_btc = None
    latest_btc_return = None
    latest_strategy_return = safe_float(latest.get("strategy_execution_return_net"))

    month_row = find_row_days_before(rows, latest_date, 30) if latest_date else None
    quarter_row = find_row_days_before(rows, latest_date, 90) if latest_date else None
    year_row = find_row_days_before(rows, latest_date, 365) if latest_date else (rows[0] if rows else None)

    latest_equity = row_value(latest, "strategy_execution_index", "real_account_index")
    latest_btc_index = row_value(latest, "btc_index")

    strategy_month = percent_change(row_value(month_row or {}, "strategy_execution_index", "real_account_index"), latest_equity)
    strategy_quarter = percent_change(row_value(quarter_row or {}, "strategy_execution_index", "real_account_index"), latest_equity)
    strategy_year = percent_change(row_value(year_row or {}, "strategy_execution_index", "real_account_index"), latest_equity)

    btc_month = percent_change(row_value(month_row or {}, "btc_index"), latest_btc_index)
    btc_quarter = percent_change(row_value(quarter_row or {}, "btc_index"), latest_btc_index)
    btc_year = percent_change(row_value(year_row or {}, "btc_index"), latest_btc_index)

    price = get_live_btc_price(None, None)
    btc_24_pct = safe_float(price.get("change24h_pct"))
    strategy_24_pct = None
    delta_24 = None

    chart_rows = []
    if rows and year_row:
        start_date = row_date(year_row)
        selected = [row for row in rows if row_date(row) and start_date and row_date(row) >= start_date]
        selected = downsample(selected, 180)
        start_strategy = row_value(selected[0], "model_index", "live_strategy_index", "strategy_execution_index") if selected else None
        start_btc = row_value(selected[0], "btc_index") if selected else None
        for row in selected:
            strategy_pct = percent_change(start_strategy, row_value(row, "model_index", "live_strategy_index", "strategy_execution_index"))
            btc_pct = percent_change(start_btc, row_value(row, "btc_index"))
            chart_rows.append(
                {
                    "date": row.get("date"),
                    "strategy_pct": strategy_pct,
                    "btc_pct": btc_pct,
                    "exposure": row_value(row, "model_authorized_exposure_x", "live_strategy_exposure_x", "strategy_execution_exposure_x", default=0.0),
                    "source": row.get("model_source") or "model_strategy",
                }
            )

    spark_rows = downsample(rows[-40:], 40)
    sparkline = [safe_float(row.get("btc_close")) for row in spark_rows if safe_float(row.get("btc_close")) is not None]
    sparkline_24h = get_btc_24h_sparkline(sparkline)

    health_summary = (health or {}).get("summary") or {}
    diagnostics_health = (diagnostics or {}).get("current_data_health_summary") or {}
    execution_intent = execution_intent_payload or (snapshot or {}).get("execution_intent") or {}
    trade_state = (diagnostics or {}).get("current_trade_state") or {}
    model_candidate_exposure = safe_float(
        (snapshot or {}).get("model_candidate_exposure")
        or trade_state.get("model_candidate_exposure")
        or latest.get("model_candidate_exposure")
        or latest.get("candidate_exposure")
    )
    target_asset = execution_intent.get("target_asset") or latest.get("execution_target_asset")
    target_exposure = safe_float(execution_intent.get("target_exposure") or latest.get("execution_target_exposure"), 0.0)
    real_is_cash = (str(target_asset or "").upper() == "CASH") or (target_exposure is not None and abs(target_exposure) < 1e-12)
    real_account_asset = "CASH" if real_is_cash else (target_asset or "n/a")
    real_account_exposure = 0.0 if real_is_cash else (target_exposure or 0.0)
    real_account_state = "Mimo trhu" if real_is_cash else "V trhu"
    trade_submission_state = "Blokované" if real_is_cash or safe_bool(health_summary.get("block_execution")) else "Pripravené"
    runtime_real_account_state = (runtime_snapshot or {}).get("real_account_state") or {}
    runtime_model_signal_state = (runtime_snapshot or {}).get("model_signal_state") or {}

    if runtime_model_signal_state:
        model_candidate_exposure = safe_float(runtime_model_signal_state.get("exposure_x"), model_candidate_exposure)

    model_preferred_asset = (
        runtime_model_signal_state.get("preferred_asset")
        or (snapshot or {}).get("candidate_asset")
        or trade_state.get("candidate_asset")
        or latest.get("candidate_asset")
    )

    if runtime_real_account_state:
        real_account_asset = runtime_real_account_state.get("asset") or real_account_asset
        real_account_exposure = safe_float(runtime_real_account_state.get("exposure_x"), real_account_exposure)
        real_in_market = safe_bool(runtime_real_account_state.get("in_market"))
        real_account_state = runtime_real_account_state.get("position_label_sk") or ("V trhu" if real_in_market else "Mimo trhu")
        trade_submission_state = "Pripravené" if safe_bool(runtime_real_account_state.get("would_place_real_order")) else "Blokované"
        target_asset = runtime_real_account_state.get("intent_target_asset") or target_asset
        target_exposure = safe_float(runtime_real_account_state.get("intent_target_size_pct"), target_exposure)
    # Direct execution truth wins over production/model fields.
    gate_status = str((real_order_gate_payload or {}).get("status") or "").strip().lower()
    would_place_real_order = safe_bool((real_order_gate_payload or {}).get("would_place_real_order"))
    direct_target_asset = execution_intent.get("target_asset")
    direct_target_exposure = safe_float(
        execution_intent.get("target_size_pct")
        or execution_intent.get("target_exposure")
        or execution_intent.get("target_exposure_x"),
        target_exposure,
    )

    if direct_target_asset:
        target_asset = direct_target_asset
    if direct_target_exposure is not None:
        target_exposure = direct_target_exposure

    if str(target_asset or "").upper() == "CASH" or abs(float(target_exposure or 0.0)) < 1e-12 or gate_status == "blocked" or not would_place_real_order:
        real_account_asset = "CASH"
        real_account_exposure = 0.0
        real_account_state = "Mimo trhu"
        trade_submission_state = "Blokované"
    dashboard_contract = dashboard_public_status or {}
    dash_real = dashboard_contract.get("real_account") or {}
    dash_exec = dashboard_contract.get("execution") or {}
    dash_model = dashboard_contract.get("model_signal") or {}
    dash_perf = dashboard_contract.get("model_performance") or {}

    # Canonical real Hyperliquid-account performance.
    # Model returns must never substitute for real-account PnL.
    dash_real_perf = dash_real.get("performance") or {}
    dash_real_current = dash_real_perf.get("current") or {}
    dash_real_windows = dash_real_perf.get("windows") or {}

    if dash_real:
        real_account_asset = dash_real.get("asset") or real_account_asset
        real_account_exposure = safe_float(dash_real.get("exposure_x"), real_account_exposure)
        real_account_state = dash_real.get("position_label_sk") or real_account_state

    if dash_exec:
        target_asset = dash_exec.get("target_asset") or target_asset
        target_exposure = safe_float(dash_exec.get("target_size_pct"), target_exposure)
        trade_submission_state = "Pripravené" if safe_bool(dash_exec.get("would_place_real_order")) else "Blokované"

    if dash_model:
        model_preferred_asset = dash_model.get("preferred_asset") or model_preferred_asset
        model_candidate_exposure = safe_float(dash_model.get("exposure_x"), model_candidate_exposure)

    live_market_state = dashboard_contract.get("live_market_state") or {}
    snapshot_btc_not_live = safe_bool(live_market_state.get("btc_24h_pct_snapshot_is_not_live"))

    if dash_perf and not safe_bool(price.get("live")) and not snapshot_btc_not_live:
        btc_24_pct = safe_float(dash_perf.get("btc_24h_pct"), btc_24_pct)

    if btc_24_pct is not None:
        price["change24h_pct"] = btc_24_pct

    # Real-account returns come only from the canonical Hyperliquid
    # cash-flow-adjusted ledger.
    if dash_real_perf:
        today_window = dash_real_windows.get("today") or {}
        month_window = dash_real_windows.get("30d") or {}
        quarter_window = dash_real_windows.get("90d") or {}

        strategy_24_pct = (
            safe_float(today_window.get("return_pct"))
            if safe_bool(today_window.get("available"))
            else None
        )
        strategy_month = (
            safe_float(month_window.get("return_pct"))
            if safe_bool(month_window.get("available"))
            else None
        )
        strategy_quarter = (
            safe_float(quarter_window.get("return_pct"))
            if safe_bool(quarter_window.get("available"))
            else None
        )
        strategy_year = None

    delta_24 = (
        strategy_24_pct - btc_24_pct
        if strategy_24_pct is not None and btc_24_pct is not None
        else None
    )

    state = {
        "strategy_version": (snapshot or {}).get("strategy_version"),
        "closed_day": (snapshot or {}).get("closed_day") or (latest or {}).get("date"),
        "current_asset": (snapshot or {}).get("current_asset"),
        "actual_held_asset": (snapshot or {}).get("actual_held_asset"),
        "candidate_asset": model_preferred_asset,
        "model_candidate_exposure": model_candidate_exposure,
        "target_asset": target_asset,
        "target_exposure": target_exposure,
        "real_account_asset": real_account_asset,
        "real_account_exposure": real_account_exposure,
        "real_account_state": real_account_state,
        "trade_submission_state": trade_submission_state,
        "effective_market_exposure": safe_float((snapshot or {}).get("effective_market_exposure") or latest.get("effective_market_exposure")),
        "trend_permission_active": safe_bool((snapshot or {}).get("trend_permission_active") or latest.get("trend_permission_active")),
        "market_state": (snapshot or {}).get("market_state") or latest.get("market_state"),
        "risk_state": (diagnostics or {}).get("current_trade_state", {}).get("state_code") or (snapshot or {}).get("execution_state"),
        "health_status": health_summary.get("overall_status") or (health or {}).get("overall_status"),
        "block_app": health_summary.get("block_app"),
        "block_execution": health_summary.get("block_execution"),
        "freshness_status": diagnostics_health.get("freshness_status") or health_summary.get("app_status"),
        "data_closed_day": diagnostics_health.get("closed_day") or health_summary.get("reference_closed_day_utc"),
        "generated_at_utc": (snapshot or {}).get("generated_at_utc") or (health or {}).get("generated_at_utc"),
        "explanation": human_strategy_text(snapshot, diagnostics),
    }
    wallet = wallet_payload(account_snapshot)
    errors = [item for item in [snapshot_error, health_error, diagnostics_error, account_error, runtime_error, execution_intent_error, real_order_gate_error, dashboard_public_error, rows_error] if item]
    return HTTPStatus.OK, {
        "ok": True,
        "timestamp": utc_now_iso(),
        "price": price,
        "btc": {
            "change24h_pct": btc_24_pct,
            "month_pct": btc_month,
            "quarter_pct": btc_quarter,
            "year_pct": btc_year,
            "sparkline": sparkline,
            "sparkline_24h": sparkline_24h.get("points"),
            "intraday_24h": sparkline_24h,
        },
        "strategy": {
            "change24h_pct": strategy_24_pct,
            "month_pct": strategy_month,
            "quarter_pct": strategy_quarter,
            "year_pct": strategy_year,
        },
        "compare": {
            "delta24h_pct": delta_24,
            "delta_month_pct": strategy_month - btc_month if strategy_month is not None and btc_month is not None else None,
            "delta_quarter_pct": strategy_quarter - btc_quarter if strategy_quarter is not None and btc_quarter is not None else None,
            "delta_year_pct": strategy_year - btc_year if strategy_year is not None and btc_year is not None else None,
        },
        "wallet": {
            **wallet,
            "month_pct": strategy_month,
            "quarter_pct": strategy_quarter,
            "month_pnl_usd": safe_float((dash_real_windows.get("30d") or {}).get("pnl_usd")),
            "quarter_pnl_usd": safe_float((dash_real_windows.get("90d") or {}).get("pnl_usd")),
            "month_available": safe_bool((dash_real_windows.get("30d") or {}).get("available")),
            "quarter_available": safe_bool((dash_real_windows.get("90d") or {}).get("available")),
            "history_days": dash_real_perf.get("history_days"),
            "live_pnl_usd": safe_float(dash_real_current.get("pnl_since_inception_usd")),
        },
        "performance": dash_real_perf,
        "state": state,
        "chart": chart_rows,
        "errors": errors,
    }
