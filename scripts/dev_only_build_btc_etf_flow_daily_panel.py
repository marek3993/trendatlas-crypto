from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pandas as pd

from research_os_dev_only_feature_anti_leakage import run_feature_output_checks
from research_os_dev_only_feature_output_common import MANDATORY_DEV_FLAGS, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]

SPOT_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"

OUTPUT_DIR = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_btc_etf_flow_daily_panel"
OUTPUT_CSV = OUTPUT_DIR / "btc_etf_flow_daily_panel.csv"
OUTPUT_CHILD_CSV = OUTPUT_DIR / "btc_etf_flow_per_etf_daily_child.csv"
OUTPUT_MANIFEST = OUTPUT_DIR / "btc_etf_flow_daily_panel.manifest.json"
OUTPUT_QUALITY = OUTPUT_DIR / "btc_etf_flow_daily_panel.quality.json"

FAMILY_ID = "btc_etf_flow_daily_panel"
FAMILY_TYPE = "dev_only_research_data_layer"

COINGLASS_FLOW_HISTORY_URL = "https://open-api-v4.coinglass.com/api/etf/bitcoin/flow-history"
COINGLASS_TICKER_HISTORY_URL = "https://open-api-v4.coinglass.com/api/etf/bitcoin/history"
SOSOVALUE_HISTORICAL_URL = "https://api.sosovalue.xyz/openapi/v2/etf/historicalInflowChart"
FARSIDE_FLOW_ALL_DATA_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"

DEFAULT_START_DATE = "2024-01-11"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_PRIMARY_PROVIDER = "coinglass"
PRIMARY_PROVIDER_ENV = "MRV1_BTC_ETF_FLOW_PRIMARY_PROVIDER"
NO_SYNTHETIC_NON_TRADING_ROWS_POLICY = (
    "emit_only_us_trading_sessions_and_shift_each_session_to_next_btc_utc_day_for_causal_use"
)

COINGLASS_PARSER_VERSION = "coinglass_api_v1"
SOSOVALUE_PARSER_VERSION = "sosovalue_api_v1"
FARSIDE_PARSER_VERSION = "farside_html_table_v1"

SUPPORTED_PRIMARY_PROVIDERS = {"coinglass", "farside"}
FARSIDE_SUMMARY_LABELS = {"Total", "Average", "Maximum", "Minimum"}
FARSIDE_MISSING_MARKERS = {"", "-", "–", "—", "n/a", "na"}
FARSIDE_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{2,10}$")
GENERIC_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PANEL_COLUMNS = [
    "date",
    "us_trading_session_date",
    "aggregate_net_flow_usd",
    "aggregate_net_flow_btc",
    "cumulative_net_flow_usd",
    "aggregate_aum_usd",
    "total_net_assets_usd",
    "total_value_traded_usd",
    "flow_positive_flag",
    "flow_3d_sum_usd",
    "flow_2_of_last_3_positive_flag",
    "btc_spot_close",
    "btc_short_price_filter_pass",
    "causal_available_for_btc_utc_day",
    "source_provider",
    "source_url",
    "source_endpoint",
    "source_retrieved_at_utc",
    "source_parser_version",
    "session_calendar_status",
    "weekend_holiday_policy",
    "missing_data_flag",
    "daily_causal_ready",
    "probe_input_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]

CHILD_COLUMNS = [
    "us_trading_session_date",
    "causal_available_for_btc_utc_day",
    "etf_ticker",
    "net_flow_usd",
    "net_flow_btc",
    "source_provider",
    "source_url",
    "source_endpoint",
    "source_retrieved_at_utc",
    "source_parser_version",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


class ConfigError(RuntimeError):
    pass


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerdictBundle:
    ready_for_dev_only_probe: bool
    verdict: str
    reason: str


class HtmlTableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._in_table = True
            self._current_table = []
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._in_row = True
            self._current_row = []
            return
        if self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            value = collapse_whitespace("".join(self._current_cell_parts))
            self._current_row.append(value)
            self._in_cell = False
            self._current_cell_parts = []
            return
        if tag == "tr" and self._in_row:
            if any(cell != "" for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = []
            self._in_row = False
            return
        if tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []
            self._in_table = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a dev-only causally aligned BTC ETF-flow daily panel."
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--start-date", type=str, default=DEFAULT_START_DATE)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--primary-provider",
        type=str,
        default=None,
        help=(
            "Primary ETF-flow provider. Defaults to env "
            f"{PRIMARY_PROVIDER_ENV} or {DEFAULT_PRIMARY_PROVIDER}."
        ),
    )
    parser.add_argument("--coinglass-api-key-env", type=str, default="MRV1_COINGLASS_API_KEY")
    parser.add_argument("--sosovalue-api-key-env", type=str, default="MRV1_SOSOVALUE_API_KEY")
    parser.add_argument(
        "--skip-sosovalue-enrichment",
        action="store_true",
        help="Disable optional SoSoValue enrichment for cumulative flow / total net assets / traded value.",
    )
    parser.add_argument(
        "--skip-coinglass-aum-build",
        action="store_true",
        help="Disable optional CoinGlass per-ticker history fetches for aggregate AUM / net assets.",
    )
    parser.add_argument(
        "--check-config-only",
        action="store_true",
        help="Validate required configuration presence and exit without network fetches or outputs.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero unless the resulting panel is READY_FOR_DEV_ONLY_PROBE.",
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def collapse_whitespace(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def with_dev_flags(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    return out


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date_cls, timedelta)):
        return str(value)
    if pd.isna(value):
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )


def parse_numeric(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def dedupe_join(items: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return "|".join(ordered)


def normalize_date(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    if isinstance(value, pd.Timestamp):
        stamp = value
    elif isinstance(value, (int, float)) and not pd.isna(value):
        magnitude = abs(int(value))
        unit = "ms" if magnitude >= 10**11 else "s"
        stamp = pd.to_datetime(int(value), unit=unit, utc=True, errors="coerce")
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            magnitude = abs(int(text))
            unit = "ms" if magnitude >= 10**11 else "s"
            stamp = pd.to_datetime(int(text), unit=unit, utc=True, errors="coerce")
        else:
            stamp = pd.to_datetime(text, utc=True, errors="coerce")

    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC").tz_localize(None).normalize()


def load_spot_daily() -> pd.Series:
    df = pd.read_csv(SPOT_PATH)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).copy()
    df["date"] = df["date"].dt.normalize()
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df.set_index("date")["close"].astype(float)


def first_non_null(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def fetch_json(
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: int,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: bytes | None = None
    request_headers = dict(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        url=url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FetchError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Network error for {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FetchError(f"Non-JSON response from {url}: {exc}") from exc


def fetch_text(*, url: str, headers: dict[str, str], timeout_seconds: int) -> str:
    request = urllib.request.Request(url=url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FetchError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Network error for {url}: {exc}") from exc


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Required environment variable {name} is not set.")
    return value


def optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def resolve_primary_provider(cli_value: str | None) -> str:
    raw = cli_value if cli_value is not None else os.environ.get(PRIMARY_PROVIDER_ENV, DEFAULT_PRIMARY_PROVIDER)
    provider = str(raw).strip().lower() or DEFAULT_PRIMARY_PROVIDER
    if provider not in SUPPORTED_PRIMARY_PROVIDERS:
        raise ConfigError(
            f"Unsupported primary provider {provider!r}. Supported values: {sorted(SUPPORTED_PRIMARY_PROVIDERS)}."
        )
    return provider


def resolve_config_status(*, primary_provider: str, coinglass_env: str, soso_env: str) -> dict[str, Any]:
    return {
        "primary_provider_env": PRIMARY_PROVIDER_ENV,
        "selected_primary_provider": primary_provider,
        "coinglass_api_key_env": coinglass_env,
        "coinglass_api_key_present": bool(optional_env(coinglass_env)),
        "sosovalue_api_key_env": soso_env,
        "sosovalue_api_key_present": bool(optional_env(soso_env)),
    }


def extract_payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        maybe_list = data.get("list")
        if isinstance(maybe_list, list):
            return [row for row in maybe_list if isinstance(row, dict)]
    return []


def validate_provider_success(payload: dict[str, Any], *, provider: str, url: str) -> None:
    code = payload.get("code")
    if code in (None, 0, "0"):
        return
    message = payload.get("msg") or payload.get("message") or "unknown error"
    raise FetchError(f"{provider} returned code={code} for {url}: {message}")


def fetch_farside_flow_html(*, timeout_seconds: int) -> str:
    return fetch_text(
        url=FARSIDE_FLOW_ALL_DATA_URL,
        headers=GENERIC_BROWSER_HEADERS,
        timeout_seconds=timeout_seconds,
    )


def parse_farside_musd(value: Any) -> float | None:
    text = collapse_whitespace("" if value is None else str(value))
    if text.lower() in FARSIDE_MISSING_MARKERS:
        return None
    cleaned = text.replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return float(cleaned)
    except ValueError as exc:
        raise FetchError(f"Unexpected Farside numeric cell value: {text!r}") from exc


def to_usd_from_musd(value_musd: float | None) -> float | None:
    if value_musd is None:
        return None
    return float(value_musd) * 1_000_000.0


def find_farside_table(html_text: str) -> tuple[list[str], list[list[str]]]:
    parser = HtmlTableExtractor()
    parser.feed(html_text)

    for table in parser.tables:
        for header_index, row in enumerate(table):
            header = [collapse_whitespace(cell) for cell in row]
            if len(header) < 3:
                continue
            if header[0] != "Date" or header[-1] != "Total":
                continue
            tickers = header[1:-1]
            if not tickers:
                raise FetchError("Farside table is missing per-ETF columns between Date and Total.")
            invalid = [ticker for ticker in tickers if not FARSIDE_TICKER_PATTERN.fullmatch(ticker)]
            if invalid:
                raise FetchError(f"Farside table contains unexpected ETF column labels: {invalid}")
            return header, table[header_index + 1 :]

    raise FetchError("Farside HTML layout changed: no table with Date/.../Total headers was found.")


def parse_farside_flow_html(
    html_text: str,
    *,
    retrieved_at_utc: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, Any]]:
    header, body_rows = find_farside_table(html_text)
    tickers = header[1:-1]
    panel_rows: list[dict[str, Any]] = []
    child_rows: list[dict[str, Any]] = []
    summary_labels_seen: list[str] = []
    raw_date_row_count = 0

    for row in body_rows:
        normalized_row = [collapse_whitespace(cell) for cell in row]
        if not any(normalized_row):
            continue
        if len(normalized_row) != len(header):
            raise FetchError(
                "Farside HTML layout changed: table row width does not match header width "
                f"({len(normalized_row)} != {len(header)})."
            )

        row_label = normalized_row[0]
        if row_label in FARSIDE_SUMMARY_LABELS:
            summary_labels_seen.append(row_label)
            continue

        session_date = pd.to_datetime(row_label, format="%d %b %Y", errors="coerce")
        if pd.isna(session_date):
            raise FetchError(
                f"Farside HTML layout changed: row label {row_label!r} is neither a supported summary label nor a date."
            )

        raw_date_row_count += 1
        session_date = pd.Timestamp(session_date).normalize()

        aggregate_net_flow_usd = to_usd_from_musd(parse_farside_musd(normalized_row[-1]))
        panel_rows.append(
            {
                "us_trading_session_date": session_date,
                "aggregate_net_flow_usd": aggregate_net_flow_usd,
                "aggregate_net_flow_btc": pd.NA,
                "provider_close_price": pd.NA,
                "source_provider": "farside",
                "source_url": FARSIDE_FLOW_ALL_DATA_URL,
                "source_endpoint": FARSIDE_FLOW_ALL_DATA_URL,
                "source_retrieved_at_utc": retrieved_at_utc,
                "source_parser_version": FARSIDE_PARSER_VERSION,
            }
        )

        for ticker, raw_value in zip(tickers, normalized_row[1:-1]):
            net_flow_usd = to_usd_from_musd(parse_farside_musd(raw_value))
            if net_flow_usd is None:
                continue
            child_rows.append(
                with_dev_flags(
                    {
                        "us_trading_session_date": session_date.strftime("%Y-%m-%d"),
                        "causal_available_for_btc_utc_day": (session_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                        "etf_ticker": ticker,
                        "net_flow_usd": net_flow_usd,
                        "net_flow_btc": pd.NA,
                        "source_provider": "farside",
                        "source_url": FARSIDE_FLOW_ALL_DATA_URL,
                        "source_endpoint": FARSIDE_FLOW_ALL_DATA_URL,
                        "source_retrieved_at_utc": retrieved_at_utc,
                        "source_parser_version": FARSIDE_PARSER_VERSION,
                    }
                )
            )

    panel = pd.DataFrame(panel_rows)
    if not panel.empty:
        panel = panel.sort_values("us_trading_session_date").drop_duplicates(
            subset=["us_trading_session_date"],
            keep="last",
        )

    child = pd.DataFrame(child_rows)
    if not child.empty:
        child = child.sort_values(["us_trading_session_date", "etf_ticker"]).drop_duplicates(
            subset=["us_trading_session_date", "etf_ticker"],
            keep="last",
        )
        for column in CHILD_COLUMNS:
            if column not in child.columns:
                child[column] = pd.NA
        child = child[CHILD_COLUMNS].copy()

    meta = {
        "primary_source_url": FARSIDE_FLOW_ALL_DATA_URL,
        "primary_source_parser_version": FARSIDE_PARSER_VERSION,
        "table_headers": header,
        "per_etf_columns": tickers,
        "summary_rows_seen": summary_labels_seen,
        "raw_date_row_count": raw_date_row_count,
    }
    return panel, child, tickers, meta


def fetch_coinglass_flow_history(*, api_key: str, timeout_seconds: int) -> dict[str, Any]:
    payload = fetch_json(
        url=COINGLASS_FLOW_HISTORY_URL,
        headers={"CG-API-KEY": api_key},
        timeout_seconds=timeout_seconds,
    )
    validate_provider_success(payload, provider="CoinGlass", url=COINGLASS_FLOW_HISTORY_URL)
    return payload


def parse_coinglass_flow_history(
    payload: dict[str, Any],
    *,
    retrieved_at_utc: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, Any]]:
    rows = extract_payload_rows(payload)
    panel_rows: list[dict[str, Any]] = []
    child_rows: list[dict[str, Any]] = []
    discovered_tickers: set[str] = set()

    for row in rows:
        session_date = normalize_date(first_non_null(row, ["date", "marketDate", "assetsDate"]))
        if session_date is None:
            continue

        aggregate_flow_usd = parse_numeric(first_non_null(row, ["changeUsd", "totalNetInflow", "netFlowUsd"]))
        aggregate_flow_btc = parse_numeric(first_non_null(row, ["changeBtc", "totalNetInflowBtc", "netFlowBtc"]))
        close_price = parse_numeric(first_non_null(row, ["closePrice", "price", "btcPrice"]))

        panel_rows.append(
            {
                "us_trading_session_date": session_date,
                "aggregate_net_flow_usd": aggregate_flow_usd,
                "aggregate_net_flow_btc": aggregate_flow_btc,
                "provider_close_price": close_price,
                "source_provider": "coinglass",
                "source_url": COINGLASS_FLOW_HISTORY_URL,
                "source_endpoint": COINGLASS_FLOW_HISTORY_URL,
                "source_retrieved_at_utc": retrieved_at_utc,
                "source_parser_version": COINGLASS_PARSER_VERSION,
            }
        )

        child_list = row.get("list")
        if not isinstance(child_list, list):
            continue

        for child in child_list:
            if not isinstance(child, dict):
                continue
            ticker = str(first_non_null(child, ["ticker", "symbol", "etfTicker"]) or "").strip().upper()
            if not ticker:
                continue
            discovered_tickers.add(ticker)
            child_rows.append(
                with_dev_flags(
                    {
                        "us_trading_session_date": session_date.strftime("%Y-%m-%d"),
                        "causal_available_for_btc_utc_day": (session_date + timedelta(days=1)).strftime("%Y-%m-%d"),
                        "etf_ticker": ticker,
                        "net_flow_usd": parse_numeric(first_non_null(child, ["changeUsd", "netFlowUsd"])),
                        "net_flow_btc": parse_numeric(first_non_null(child, ["changeBtc", "netFlowBtc"])),
                        "source_provider": "coinglass",
                        "source_url": COINGLASS_FLOW_HISTORY_URL,
                        "source_endpoint": COINGLASS_FLOW_HISTORY_URL,
                        "source_retrieved_at_utc": retrieved_at_utc,
                        "source_parser_version": COINGLASS_PARSER_VERSION,
                    }
                )
            )

    panel = pd.DataFrame(panel_rows)
    if not panel.empty:
        panel = panel.sort_values("us_trading_session_date").drop_duplicates(
            subset=["us_trading_session_date"], keep="last"
        )

    child = pd.DataFrame(child_rows)
    if not child.empty:
        child = child.sort_values(["us_trading_session_date", "etf_ticker"]).drop_duplicates(
            subset=["us_trading_session_date", "etf_ticker"],
            keep="last",
        )
        for column in CHILD_COLUMNS:
            if column not in child.columns:
                child[column] = pd.NA
        child = child[CHILD_COLUMNS].copy()

    meta = {
        "primary_source_url": COINGLASS_FLOW_HISTORY_URL,
        "primary_source_parser_version": COINGLASS_PARSER_VERSION,
        "raw_date_row_count": int(len(panel)),
    }
    return panel, child, sorted(discovered_tickers), meta


def fetch_coinglass_ticker_history(
    *,
    api_key: str,
    ticker: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    url = f"{COINGLASS_TICKER_HISTORY_URL}?ticker={ticker}"
    payload = fetch_json(
        url=url,
        headers={"CG-API-KEY": api_key},
        timeout_seconds=timeout_seconds,
    )
    validate_provider_success(payload, provider="CoinGlass", url=url)
    return payload


def parse_coinglass_ticker_histories(
    *,
    api_key: str,
    tickers: list[str],
    timeout_seconds: int,
) -> pd.DataFrame:
    history_rows: list[dict[str, Any]] = []

    for ticker in tickers:
        payload = fetch_coinglass_ticker_history(
            api_key=api_key,
            ticker=ticker,
            timeout_seconds=timeout_seconds,
        )
        for row in extract_payload_rows(payload):
            session_date = normalize_date(first_non_null(row, ["marketDate", "assetsDate", "date"]))
            net_assets = parse_numeric(first_non_null(row, ["netAssets", "totalNetAssets"]))
            if session_date is None or net_assets is None:
                continue
            history_rows.append(
                {
                    "us_trading_session_date": session_date,
                    "etf_ticker": ticker,
                    "net_assets_usd": net_assets,
                }
            )
        time.sleep(0.10)

    history = pd.DataFrame(history_rows)
    if history.empty:
        return history

    history = history.sort_values(["us_trading_session_date", "etf_ticker"]).drop_duplicates(
        subset=["us_trading_session_date", "etf_ticker"],
        keep="last",
    )
    aggregated = (
        history.groupby("us_trading_session_date", dropna=True)["net_assets_usd"]
        .sum()
        .rename("aggregate_aum_usd")
        .to_frame()
    )
    aggregated["total_net_assets_usd"] = aggregated["aggregate_aum_usd"]
    return aggregated


def fetch_sosovalue_history(*, api_key: str, timeout_seconds: int) -> dict[str, Any]:
    payload = fetch_json(
        url=SOSOVALUE_HISTORICAL_URL,
        headers={"x-soso-api-key": api_key},
        timeout_seconds=timeout_seconds,
        method="POST",
        payload={"type": "us-btc-spot"},
    )
    validate_provider_success(payload, provider="SoSoValue", url=SOSOVALUE_HISTORICAL_URL)
    return payload


def parse_sosovalue_history(payload: dict[str, Any]) -> pd.DataFrame:
    rows = extract_payload_rows(payload)
    parsed: list[dict[str, Any]] = []
    for row in rows:
        session_date = normalize_date(row.get("date"))
        if session_date is None:
            continue
        parsed.append(
            {
                "us_trading_session_date": session_date,
                "soso_total_net_inflow_usd": parse_numeric(row.get("totalNetInflow")),
                "cumulative_net_flow_usd": parse_numeric(row.get("cumNetInflow")),
                "total_value_traded_usd": parse_numeric(row.get("totalValueTraded")),
                "total_net_assets_usd_soso": parse_numeric(row.get("totalNetAssets")),
            }
        )

    out = pd.DataFrame(parsed)
    if out.empty:
        return out
    return out.sort_values("us_trading_session_date").drop_duplicates(
        subset=["us_trading_session_date"],
        keep="last",
    )


def nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> date_cls:
    day = date_cls(year, month, 1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    day += timedelta(days=7 * (occurrence - 1))
    return day


def last_weekday_of_month(year: int, month: int, weekday: int) -> date_cls:
    if month == 12:
        day = date_cls(year + 1, 1, 1) - timedelta(days=1)
    else:
        day = date_cls(year, month + 1, 1) - timedelta(days=1)
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return day


def observed_fixed_holiday(year: int, month: int, day: int) -> date_cls:
    holiday = date_cls(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def easter_sunday(year: int) -> date_cls:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date_cls(year, month, day)


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> set[date_cls]:
    easter = easter_sunday(year)
    return {
        observed_fixed_holiday(year, 1, 1),
        nth_weekday_of_month(year, 1, 0, 3),   # MLK Day
        nth_weekday_of_month(year, 2, 0, 3),   # Presidents Day
        easter - timedelta(days=2),            # Good Friday
        last_weekday_of_month(year, 5, 0),     # Memorial Day
        observed_fixed_holiday(year, 6, 19),   # Juneteenth
        observed_fixed_holiday(year, 7, 4),    # Independence Day
        nth_weekday_of_month(year, 9, 0, 1),   # Labor Day
        nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving
        observed_fixed_holiday(year, 12, 25),  # Christmas
    }


def classify_session_date(session_date: pd.Timestamp) -> str:
    day = session_date.date()
    if session_date.weekday() >= 5:
        return "unexpected_weekend_session"
    if day in nyse_holidays(session_date.year):
        return "unexpected_nyse_holiday_session"
    return "us_trading_day"


def iter_expected_trading_days(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    days: list[str] = []
    cursor = start
    while cursor <= end:
        if classify_session_date(cursor) == "us_trading_day":
            days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days


def summarize_field_coverage(panel: pd.DataFrame, column: str) -> dict[str, Any]:
    present = panel[column].notna()
    if not present.any():
        return {"non_null_count": 0, "first_non_null_date": None, "last_non_null_date": None}
    dates = panel.loc[present, "us_trading_session_date"].astype(str).tolist()
    return {
        "non_null_count": int(present.sum()),
        "first_non_null_date": dates[0],
        "last_non_null_date": dates[-1],
    }


def derive_verdict(panel: pd.DataFrame) -> VerdictBundle:
    if panel.empty:
        return VerdictBundle(
            ready_for_dev_only_probe=False,
            verdict="NEED_DATA_PLUMBING_FIRST",
            reason="No CoinGlass ETF-flow rows were materialized into the dev-only panel.",
        )

    ready_days = int(panel["daily_causal_ready"].fillna(False).sum())
    if ready_days == 0:
        return VerdictBundle(
            ready_for_dev_only_probe=False,
            verdict="NEED_DATA_PLUMBING_FIRST",
            reason="ETF-flow rows exist but none satisfy the strict daily causal readiness checks.",
        )

    return VerdictBundle(
        ready_for_dev_only_probe=True,
        verdict="READY_FOR_DEV_ONLY_PROBE",
        reason=(
            "Causal ETF-flow rows are available. btc_short_price_filter_pass remains intentionally null because "
            "strategy logic is out of scope, but the raw BTC spot close needed for that downstream leg is present."
        ),
    )


def build_panel(
    *,
    primary_provider: str,
    start_date_text: str,
    timeout_seconds: int,
    coinglass_api_key: str | None,
    sosovalue_api_key: str | None,
    build_soso_enrichment: bool,
    build_coinglass_aum: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    retrieved_at_utc = timestamp_utc()
    spot_close = load_spot_daily()
    start_date = pd.Timestamp(start_date_text).normalize()

    primary_meta: dict[str, Any]
    if primary_provider == "coinglass":
        if not coinglass_api_key:
            raise ConfigError("CoinGlass primary provider was selected but no CoinGlass API key was supplied.")
        coinglass_payload = fetch_coinglass_flow_history(
            api_key=coinglass_api_key,
            timeout_seconds=timeout_seconds,
        )
        flow_panel, child_table, discovered_tickers, primary_meta = parse_coinglass_flow_history(
            coinglass_payload,
            retrieved_at_utc=retrieved_at_utc,
        )
        if flow_panel.empty:
            raise FetchError("CoinGlass flow-history returned no parseable BTC ETF-flow rows.")
    elif primary_provider == "farside":
        farside_html = fetch_farside_flow_html(timeout_seconds=timeout_seconds)
        flow_panel, child_table, discovered_tickers, primary_meta = parse_farside_flow_html(
            farside_html,
            retrieved_at_utc=retrieved_at_utc,
        )
        if flow_panel.empty:
            raise FetchError("Farside returned no parseable BTC ETF-flow rows.")
    else:
        raise ConfigError(f"Unsupported primary provider {primary_provider!r}.")

    flow_panel = flow_panel.loc[flow_panel["us_trading_session_date"] >= start_date].copy()
    if flow_panel.empty:
        raise FetchError(
            f"{primary_provider} returned rows, but none are on or after start_date={start_date_text}."
        )

    dropped_non_trading_provider_rows: list[str] = []
    if primary_provider == "farside":
        flow_panel["session_calendar_status"] = flow_panel["us_trading_session_date"].apply(classify_session_date)
        dropped_non_trading_provider_rows = flow_panel.loc[
            flow_panel["session_calendar_status"] != "us_trading_day",
            "us_trading_session_date",
        ].dt.strftime("%Y-%m-%d").tolist()
        if dropped_non_trading_provider_rows:
            flow_panel = flow_panel.loc[flow_panel["session_calendar_status"] == "us_trading_day"].copy()
            if child_table.empty:
                child_table = child_table.copy()
            else:
                valid_session_dates = set(flow_panel["us_trading_session_date"].dt.strftime("%Y-%m-%d").tolist())
                child_table = child_table.loc[
                    child_table["us_trading_session_date"].isin(valid_session_dates)
                ].copy()
        flow_panel = flow_panel.drop(columns=["session_calendar_status"], errors="ignore")
        if flow_panel.empty:
            raise FetchError("Farside rows exist, but none map to U.S. trading sessions after filtering.")

    aum_panel = pd.DataFrame()
    if primary_provider == "coinglass" and build_coinglass_aum and discovered_tickers:
        aum_panel = parse_coinglass_ticker_histories(
            api_key=str(coinglass_api_key),
            tickers=discovered_tickers,
            timeout_seconds=timeout_seconds,
        )
        if not aum_panel.empty:
            aum_panel = aum_panel.loc[aum_panel.index >= start_date]

    soso_panel = pd.DataFrame()
    if build_soso_enrichment and sosovalue_api_key:
        soso_payload = fetch_sosovalue_history(
            api_key=sosovalue_api_key,
            timeout_seconds=timeout_seconds,
        )
        soso_panel = parse_sosovalue_history(soso_payload)
        if not soso_panel.empty:
            soso_panel = soso_panel.loc[soso_panel["us_trading_session_date"] >= start_date].copy()

    panel = flow_panel.copy().sort_values("us_trading_session_date").reset_index(drop=True)
    if not aum_panel.empty:
        panel = panel.merge(
            aum_panel.reset_index(),
            on="us_trading_session_date",
            how="left",
        )

    if not soso_panel.empty:
        panel = panel.merge(soso_panel, on="us_trading_session_date", how="left")
        panel["cumulative_net_flow_usd"] = panel["cumulative_net_flow_usd"]
        panel["total_value_traded_usd"] = panel["total_value_traded_usd"]
        panel["total_net_assets_usd"] = panel["total_net_assets_usd"].combine_first(
            panel["total_net_assets_usd_soso"]
        )
    else:
        panel["cumulative_net_flow_usd"] = pd.NA
        panel["total_value_traded_usd"] = pd.NA
        if "total_net_assets_usd" not in panel.columns:
            panel["total_net_assets_usd"] = pd.NA

    if "aggregate_aum_usd" not in panel.columns:
        panel["aggregate_aum_usd"] = pd.NA
    if "total_net_assets_usd" not in panel.columns:
        panel["total_net_assets_usd"] = pd.NA

    panel["session_calendar_status"] = panel["us_trading_session_date"].apply(classify_session_date)
    panel["causal_available_for_btc_utc_day"] = panel["us_trading_session_date"] + timedelta(days=1)
    panel["date"] = panel["causal_available_for_btc_utc_day"]
    panel["btc_spot_close"] = panel["us_trading_session_date"].map(spot_close)
    panel["flow_positive_flag"] = (panel["aggregate_net_flow_usd"] > 0).astype("boolean")
    panel.loc[panel["aggregate_net_flow_usd"].isna(), "flow_positive_flag"] = pd.NA
    panel["flow_3d_sum_usd"] = panel["aggregate_net_flow_usd"].rolling(3, min_periods=3).sum()

    positive_int = panel["flow_positive_flag"].map({True: 1, False: 0}).astype("Float64")
    positive_sum = positive_int.rolling(3, min_periods=3).sum()
    panel["flow_2_of_last_3_positive_flag"] = (positive_sum >= 2).astype("boolean")
    panel.loc[positive_sum.isna(), "flow_2_of_last_3_positive_flag"] = pd.NA

    source_provider = primary_provider
    if not soso_panel.empty:
        source_provider = f"{primary_provider}+optional_sosovalue_enrichment"
    panel["source_provider"] = source_provider

    primary_source_url = str(primary_meta["primary_source_url"])
    primary_parser_version = str(primary_meta["primary_source_parser_version"])

    def endpoint_string(row: pd.Series) -> str:
        endpoints = [primary_source_url]
        if pd.notna(row.get("aggregate_aum_usd")):
            endpoints.append(COINGLASS_TICKER_HISTORY_URL)
        if pd.notna(row.get("cumulative_net_flow_usd")) or pd.notna(row.get("total_value_traded_usd")):
            endpoints.append(SOSOVALUE_HISTORICAL_URL)
        return dedupe_join(endpoints)

    def parser_version_string(row: pd.Series) -> str:
        versions = [primary_parser_version]
        if pd.notna(row.get("aggregate_aum_usd")):
            versions.append(COINGLASS_PARSER_VERSION)
        if pd.notna(row.get("cumulative_net_flow_usd")) or pd.notna(row.get("total_value_traded_usd")):
            versions.append(SOSOVALUE_PARSER_VERSION)
        return dedupe_join(versions)

    panel["source_url"] = panel.apply(endpoint_string, axis=1)
    panel["source_endpoint"] = panel.apply(endpoint_string, axis=1)
    panel["source_retrieved_at_utc"] = retrieved_at_utc
    panel["source_parser_version"] = panel.apply(parser_version_string, axis=1)
    panel["weekend_holiday_policy"] = NO_SYNTHETIC_NON_TRADING_ROWS_POLICY
    panel["btc_short_price_filter_pass"] = pd.NA

    panel["missing_data_flag"] = (
        panel["aggregate_net_flow_usd"].isna()
        | panel["btc_spot_close"].isna()
        | (panel["session_calendar_status"] != "us_trading_day")
    )
    panel["daily_causal_ready"] = ~panel["missing_data_flag"]
    panel["probe_input_ready_flag"] = panel["daily_causal_ready"]

    panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")
    panel["us_trading_session_date"] = panel["us_trading_session_date"].dt.strftime("%Y-%m-%d")
    panel["causal_available_for_btc_utc_day"] = panel["causal_available_for_btc_utc_day"].dt.strftime("%Y-%m-%d")

    for flag_column, flag_value in MANDATORY_DEV_FLAGS.items():
        panel[flag_column] = flag_value

    for column in PANEL_COLUMNS:
        if column not in panel.columns:
            panel[column] = pd.NA
    panel = panel[PANEL_COLUMNS].copy()

    if not child_table.empty:
        child_table = child_table.loc[child_table["us_trading_session_date"] >= start_date.strftime("%Y-%m-%d")].copy()
        for column in CHILD_COLUMNS:
            if column not in child_table.columns:
                child_table[column] = pd.NA
        child_table = child_table[CHILD_COLUMNS].copy()

    observed_sessions = panel["us_trading_session_date"].tolist()
    expected_sessions = iter_expected_trading_days(
        pd.Timestamp(panel["us_trading_session_date"].iloc[0]),
        pd.Timestamp(panel["us_trading_session_date"].iloc[-1]),
    )
    missing_expected = sorted(set(expected_sessions) - set(observed_sessions))
    unexpected_non_trading = panel.loc[
        panel["session_calendar_status"] != "us_trading_day",
        "us_trading_session_date",
    ].tolist()

    overlap = pd.DataFrame()
    if "soso_total_net_inflow_usd" in panel.columns and panel["soso_total_net_inflow_usd"].notna().any():
        overlap = panel.loc[
            panel["aggregate_net_flow_usd"].notna() & panel["soso_total_net_inflow_usd"].notna(),
            ["us_trading_session_date", "aggregate_net_flow_usd", "soso_total_net_inflow_usd"],
        ].copy()
        overlap["abs_diff_usd"] = (overlap["aggregate_net_flow_usd"] - overlap["soso_total_net_inflow_usd"]).abs()

    manifest_meta = {
        "primary_provider": primary_provider,
        "primary_source_url": primary_source_url,
        "primary_source_parser_version": primary_parser_version,
        "discovered_etf_tickers": discovered_tickers,
        "primary_provider_row_count": int(len(flow_panel)),
        "primary_provider_child_row_count": int(len(child_table)),
        "primary_provider_meta": primary_meta,
        "primary_provider_non_trading_rows_dropped": dropped_non_trading_provider_rows,
        "coinglass_aum_enabled": bool(primary_provider == "coinglass" and build_coinglass_aum),
        "coinglass_aum_coverage_rows": int(0 if aum_panel.empty else len(aum_panel)),
        "sosovalue_enrichment_enabled": bool(build_soso_enrichment and sosovalue_api_key),
        "sosovalue_overlap_rows": int(len(overlap)),
        "price_filter_contract_status": (
            "btc_short_price_filter_pass is intentionally reserved-null in this data layer; "
            "raw btc_spot_close is provided for downstream strategy-leg materialization."
        ),
    }

    verdict = derive_verdict(panel)
    quality = {
        "panel_start_session_date": panel["us_trading_session_date"].iloc[0],
        "panel_end_session_date": panel["us_trading_session_date"].iloc[-1],
        "panel_start_causal_btc_utc_day": panel["date"].iloc[0],
        "panel_end_causal_btc_utc_day": panel["date"].iloc[-1],
        "row_count": int(len(panel)),
        "child_row_count": int(len(child_table)),
        "field_coverage": {
            "aggregate_net_flow_usd": summarize_field_coverage(panel, "aggregate_net_flow_usd"),
            "aggregate_net_flow_btc": summarize_field_coverage(panel, "aggregate_net_flow_btc"),
            "cumulative_net_flow_usd": summarize_field_coverage(panel, "cumulative_net_flow_usd"),
            "aggregate_aum_usd": summarize_field_coverage(panel, "aggregate_aum_usd"),
            "total_net_assets_usd": summarize_field_coverage(panel, "total_net_assets_usd"),
            "total_value_traded_usd": summarize_field_coverage(panel, "total_value_traded_usd"),
        },
        "calendar_audit": {
            "expected_us_trading_sessions_in_range": len(expected_sessions),
            "observed_us_trading_sessions_in_range": len(observed_sessions),
            "missing_expected_us_trading_sessions": missing_expected,
            "unexpected_non_trading_session_dates": unexpected_non_trading,
        },
        "cross_provider_validation": {
            "overlap_days": int(len(overlap)),
            "max_abs_diff_usd": None if overlap.empty else float(overlap["abs_diff_usd"].max()),
            "median_abs_diff_usd": None if overlap.empty else float(overlap["abs_diff_usd"].median()),
        },
        "daily_causal_ready_days": int(panel["daily_causal_ready"].sum()),
        "probe_input_ready_days": int(panel["probe_input_ready_flag"].sum()),
        "ready_for_dev_only_probe": verdict.ready_for_dev_only_probe,
        "verdict": verdict.verdict,
        "verdict_reason": verdict.reason,
        "limitations": [
            f"{primary_provider} is the primary dev-only source; outputs remain non-authoritative.",
            "aggregate_net_flow_btc stays null unless the provider exposes a machine-readable BTC-denominated flow field.",
            "btc_short_price_filter_pass stays null by design because strategy logic is explicitly out of scope for this task.",
            "No synthetic weekend or NYSE-holiday rows are emitted; rolling flow features use consecutive U.S. trading sessions only.",
        ],
    }

    if primary_provider == "farside":
        quality["limitations"].append(
            "Farside is a public HTML table rather than a formal API contract; parser logic fails closed on header or row-shape changes."
        )

    if not manifest_meta["sosovalue_enrichment_enabled"]:
        quality["limitations"].append(
            "SoSoValue enrichment is unavailable, so cumulative_net_flow_usd / total_value_traded_usd may remain null."
        )
    if not manifest_meta["coinglass_aum_coverage_rows"]:
        quality["limitations"].append(
            "CoinGlass per-ticker history did not yield aggregate AUM coverage, so aggregate_aum_usd may remain null."
        )
    if missing_expected:
        quality["limitations"].append(
            f"Missing expected U.S. trading sessions inside observed range: {missing_expected}"
        )

    return panel, child_table, manifest_meta, quality


def build_manifest(
    *,
    output_dir: Path,
    config_status: dict[str, Any],
    manifest_meta: dict[str, Any],
) -> dict[str, Any]:
    primary_provider = str(manifest_meta["primary_provider"])
    input_refs = [
        str(SPOT_PATH),
        str(manifest_meta["primary_source_url"]),
    ]
    if manifest_meta.get("coinglass_aum_enabled"):
        input_refs.append(COINGLASS_TICKER_HISTORY_URL)
    input_refs.append(SOSOVALUE_HISTORICAL_URL)

    required_env = []
    if primary_provider == "coinglass":
        required_env.append(config_status["coinglass_api_key_env"])

    return with_dev_flags(
        {
            "artifact_type": "dev_only_btc_etf_flow_daily_panel_manifest",
            "artifact_id": FAMILY_ID,
            "generated_at_utc": timestamp_utc(),
            "family_id": FAMILY_ID,
            "family_type": FAMILY_TYPE,
            "output_files": {
                "panel_csv": str(output_dir / OUTPUT_CSV.name),
                "per_etf_child_csv": str(output_dir / OUTPUT_CHILD_CSV.name),
                "manifest_json": str(output_dir / OUTPUT_MANIFEST.name),
                "quality_json": str(output_dir / OUTPUT_QUALITY.name),
            },
            "input_refs": input_refs,
            "env_config": {
                "required": required_env,
                "optional": [config_status["sosovalue_api_key_env"]],
                "resolved_presence": config_status,
            },
            "column_schema": PANEL_COLUMNS,
            "per_etf_child_schema": CHILD_COLUMNS,
            "causal_alignment_rule": {
                "us_trading_session_date": "The U.S. ETF trading session date supplied by the provider.",
                "date": "The BTC UTC day on which the prior U.S. trading-session ETF data first becomes causally usable.",
                "causal_available_for_btc_utc_day": "Equal to date. It is us_trading_session_date + 1 calendar day.",
                "btc_spot_close": "Joined from BTCUSDT daily spot close on us_trading_session_date, not on the shifted causal day.",
                "weekend_holiday_policy": NO_SYNTHETIC_NON_TRADING_ROWS_POLICY,
                "rolling_window_policy": "flow_3d_sum_usd and flow_2_of_last_3_positive_flag roll across the last three U.S. trading sessions only.",
            },
            "source_selection": {
                "primary_provider": primary_provider,
                "fallback_activation_env": PRIMARY_PROVIDER_ENV,
                "available_primary_providers": {
                    "coinglass": (
                        "Preferred paid provider. CoinGlass flow-history exposes machine-readable historical aggregate "
                        "BTC ETF flow plus per-ETF breakdown."
                    ),
                    "farside": (
                        "Free dev-only fallback. Farside exposes a public HTML table with daily per-ETF USD flows "
                        "and aggregate total flow."
                    ),
                },
                "optional_secondary_provider": "sosovalue",
                "optional_secondary_role": "Aggregate enrichment and cross-provider validation only.",
            },
            "status": "generated_dev_only_research_data_layer",
            "panel_level_meta": manifest_meta,
        }
    )


def main() -> None:
    try:
        args = parse_args()
        primary_provider = resolve_primary_provider(args.primary_provider)
        config_status = resolve_config_status(
            primary_provider=primary_provider,
            coinglass_env=args.coinglass_api_key_env,
            soso_env=args.sosovalue_api_key_env,
        )

        if args.check_config_only:
            print(json.dumps(config_status, indent=2))
            if primary_provider == "coinglass" and not config_status["coinglass_api_key_present"]:
                raise SystemExit(2)
            raise SystemExit(0)

        coinglass_api_key = None
        if primary_provider == "coinglass":
            coinglass_api_key = require_env(args.coinglass_api_key_env)
        sosovalue_api_key = None if args.skip_sosovalue_enrichment else optional_env(args.sosovalue_api_key_env)

        output_dir = Path(args.output_dir)
        ensure_dir(output_dir)

        panel, child_table, manifest_meta, quality = build_panel(
            primary_provider=primary_provider,
            start_date_text=str(args.start_date).strip() or DEFAULT_START_DATE,
            timeout_seconds=int(args.timeout_seconds),
            coinglass_api_key=coinglass_api_key,
            sosovalue_api_key=sosovalue_api_key,
            build_soso_enrichment=not args.skip_sosovalue_enrichment,
            build_coinglass_aum=not args.skip_coinglass_aum_build,
        )

        panel_path = output_dir / OUTPUT_CSV.name
        child_path = output_dir / OUTPUT_CHILD_CSV.name
        manifest_path = output_dir / OUTPUT_MANIFEST.name
        quality_path = output_dir / OUTPUT_QUALITY.name

        panel.to_csv(panel_path, index=False)
        child_table.to_csv(child_path, index=False)

        checks = run_feature_output_checks(
            columns=PANEL_COLUMNS,
            required_columns=PANEL_COLUMNS,
            rows=panel.to_dict(orient="records"),
        )

        manifest = build_manifest(
            output_dir=output_dir,
            config_status=config_status,
            manifest_meta=manifest_meta,
        )
        manifest["row_count"] = int(len(panel))

        quality_payload = with_dev_flags(
            {
                "artifact_type": "dev_only_btc_etf_flow_daily_panel_quality",
                "artifact_id": f"{FAMILY_ID}_quality",
                "generated_at_utc": timestamp_utc(),
                "family_id": FAMILY_ID,
                "required_columns": PANEL_COLUMNS,
                "leakage_checks": checks,
                "status": "passed" if all(item["ok"] for item in checks) else "failed",
                **quality,
            }
        )

        write_json(manifest_path, manifest)
        write_json(quality_path, quality_payload)

        print(f"{FAMILY_ID} dev-only output generated")
        print(panel_path)
        print(child_path)
        print(manifest_path)
        print(quality_path)
        print(f"verdict={quality_payload['verdict']}")
        print(f"ready_for_dev_only_probe={quality_payload['ready_for_dev_only_probe']}")

        if args.require_ready and not quality_payload["ready_for_dev_only_probe"]:
            raise SystemExit(1)
    except ConfigError as exc:
        print(f"verdict=NEED_DATA_PLUMBING_FIRST")
        print(f"blocker={exc}")
        raise SystemExit(2) from exc
    except FetchError as exc:
        print("verdict=NEED_DATA_PLUMBING_FIRST")
        print(f"blocker={exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
