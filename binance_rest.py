from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests

from config import SETTINGS


class BinanceRESTError(RuntimeError):
    pass


class BinanceFuturesREST:
    def __init__(self) -> None:
        self.base = SETTINGS.binance_rest_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "lottery-research-bot/1.0"})

    def _sleep(self) -> None:
        time.sleep(SETTINGS.rest_sleep_sec)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}{path}"
        r = self.session.get(url, params=params or {}, timeout=SETTINGS.request_timeout_sec)
        if r.status_code != 200:
            raise BinanceRESTError(f"{path} failed: {r.status_code} {r.text}")
        return r.json()

    @staticmethod
    def symbol_to_pair(symbol: str) -> str:
        return symbol

    def _paginate_klines(
        self,
        path: str,
        params: dict[str, Any],
        start_ms: int,
        end_ms: int,
        limit: int,
    ) -> list[list[Any]]:
        out: list[list[Any]] = []
        cursor = start_ms

        while cursor <= end_ms:
            p = dict(params)
            p.update({"startTime": cursor, "endTime": end_ms, "limit": limit})
            rows = self._get(path, p)
            if not rows:
                break

            out.extend(rows)
            last_open = int(rows[-1][0])
            next_cursor = last_open + 1
            if next_cursor <= cursor:
                break

            cursor = next_cursor
            self._sleep()

            if len(rows) < limit:
                break

        return out

    def _paginate_stats(
        self,
        path: str,
        params: dict[str, Any],
        start_ms: int,
        end_ms: int,
        time_key: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = start_ms

        while cursor <= end_ms:
            p = dict(params)
            p.update({"startTime": cursor, "endTime": end_ms, "limit": limit})
            rows = self._get(path, p)
            if not rows:
                break

            out.extend(rows)
            last_ts = int(rows[-1][time_key])
            next_cursor = last_ts + 1
            if next_cursor <= cursor:
                break

            cursor = next_cursor
            self._sleep()

            if len(rows) < limit:
                break

        return out

    @staticmethod
    def _df_from_klines(rows: list[list[Any]], prefix: str = "") -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()

        cols = [
            "open_time",
            f"{prefix}open",
            f"{prefix}high",
            f"{prefix}low",
            f"{prefix}close",
            "volume",
            "close_time",
            "quote_volume",
            "trade_count",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        df = pd.DataFrame(rows, columns=cols)

        for c in df.columns:
            if c not in {"open_time", "close_time"}:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df["ts_open_utc"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["ts_close_utc"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

        return df.drop(columns=["open_time", "close_time", "ignore"])

    @staticmethod
    def _df_from_simple_stats(rows: list[dict[str, Any]], ts_key: str = "timestamp") -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        for c in df.columns:
            if c not in {"symbol", "pair", ts_key}:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df["ts_utc"] = pd.to_datetime(df[ts_key].astype("int64"), unit="ms", utc=True)
        return df

    def get_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_klines(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval},
            start_ms,
            end_ms,
            SETTINGS.kline_limit,
        )
        df = self._df_from_klines(rows)
        if not df.empty:
            df.insert(0, "symbol", symbol)
        return df

    def get_index_klines(self, pair: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_klines(
            "/fapi/v1/indexPriceKlines",
            {"pair": pair, "interval": interval},
            start_ms,
            end_ms,
            SETTINGS.kline_limit,
        )
        df = self._df_from_klines(rows, prefix="index_")
        if not df.empty:
            df.insert(0, "pair", pair)
        return df

    def get_premium_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_klines(
            "/fapi/v1/premiumIndexKlines",
            {"symbol": symbol, "interval": interval},
            start_ms,
            end_ms,
            SETTINGS.kline_limit,
        )
        df = self._df_from_klines(rows, prefix="premium_")
        if not df.empty:
            df.insert(0, "symbol", symbol)
        return df

    def get_funding_rate(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_stats(
            "/fapi/v1/fundingRate",
            {"symbol": symbol},
            start_ms,
            end_ms,
            time_key="fundingTime",
            limit=SETTINGS.funding_limit,
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["funding_time_utc"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
        df["funding_rate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
        df["mark_price"] = pd.to_numeric(df["markPrice"], errors="coerce")
        return df[["symbol", "funding_time_utc", "funding_rate", "mark_price"]]

    def get_funding_info(self) -> pd.DataFrame:
        rows = self._get("/fapi/v1/fundingInfo")
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        for c in ("adjustedFundingRateCap", "adjustedFundingRateFloor", "fundingIntervalHours"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        return df.rename(
            columns={
                "adjustedFundingRateCap": "adjusted_funding_rate_cap",
                "adjustedFundingRateFloor": "adjusted_funding_rate_floor",
                "fundingIntervalHours": "funding_interval_hours",
            }
        )

    def get_basis(self, pair: str, period: str, start_ms: int, end_ms: int, contract_type: str = "PERPETUAL") -> pd.DataFrame:
        rows = self._paginate_stats(
            "/futures/data/basis",
            {"pair": pair, "period": period, "contractType": contract_type},
            start_ms,
            end_ms,
            time_key="timestamp",
            limit=SETTINGS.stats_limit,
        )
        df = self._df_from_simple_stats(rows)
        if df.empty:
            return df

        df["symbol"] = pair
        return df.rename(
            columns={
                "indexPrice": "index_price",
                "contractPrice": "contract_price",
                "basisRate": "basis_rate",
                "annualizedBasisRate": "annualized_basis_rate",
            }
        )

    def get_open_interest_hist(self, symbol: str, period: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_stats(
            "/futures/data/openInterestHist",
            {"symbol": symbol, "period": period},
            start_ms,
            end_ms,
            time_key="timestamp",
            limit=SETTINGS.stats_limit,
        )
        df = self._df_from_simple_stats(rows)
        if df.empty:
            return df

        return df.rename(
            columns={
                "sumOpenInterest": "oi_contracts",
                "sumOpenInterestValue": "oi_value",
            }
        )

    def get_taker_volume(self, symbol: str, period: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_stats(
            "/futures/data/takerlongshortRatio",
            {"symbol": symbol, "period": period},
            start_ms,
            end_ms,
            time_key="timestamp",
            limit=SETTINGS.stats_limit,
        )
        df = self._df_from_simple_stats(rows)
        if df.empty:
            return df

        return df.rename(
            columns={
                "buySellRatio": "buy_sell_ratio",
                "buyVol": "buy_vol",
                "sellVol": "sell_vol",
            }
        )

    def get_global_long_short(self, symbol: str, period: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_stats(
            "/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period},
            start_ms,
            end_ms,
            time_key="timestamp",
            limit=SETTINGS.stats_limit,
        )
        df = self._df_from_simple_stats(rows)
        if df.empty:
            return df

        return df.rename(
            columns={
                "longShortRatio": "long_short_ratio",
                "longAccount": "long_account",
                "shortAccount": "short_account",
            }
        )

    def get_top_trader_position_ratio(self, symbol: str, period: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_stats(
            "/futures/data/topLongShortPositionRatio",
            {"symbol": symbol, "period": period},
            start_ms,
            end_ms,
            time_key="timestamp",
            limit=SETTINGS.stats_limit,
        )
        df = self._df_from_simple_stats(rows)
        if df.empty:
            return df

        return df.rename(
            columns={
                "longShortRatio": "top_long_short_ratio",
                "longAccount": "top_long_account",
                "shortAccount": "top_short_account",
            }
        )

    def get_top_trader_account_ratio(self, symbol: str, period: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        rows = self._paginate_stats(
            "/futures/data/topLongShortAccountRatio",
            {"symbol": symbol, "period": period},
            start_ms,
            end_ms,
            time_key="timestamp",
            limit=SETTINGS.stats_limit,
        )
        df = self._df_from_simple_stats(rows)
        if df.empty:
            return df

        return df.rename(
            columns={
                "longShortRatio": "top_long_short_ratio",
                "longAccount": "top_long_account",
                "shortAccount": "top_short_account",
            }
        )