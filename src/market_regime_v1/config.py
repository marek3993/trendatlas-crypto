from dataclasses import dataclass, field


@dataclass(slots=True)
class Thresholds:
    bullish_entry: float = 60.0
    bullish_hold: float = 25.0
    bearish_entry: float = -60.0
    bearish_hold: float = -25.0
    min_conf_entry: float = 55.0
    min_conf_hold: float = 40.0
    hard_flip: float = 75.0
    mr_hot_threshold: float = 60.0


@dataclass(slots=True)
class RiskConfig:
    target_vol_annual: float = 0.20
    max_leverage: float = 2.0
    min_leverage: float = 1.0
    max_daily_loss: float = 0.03
    max_positions: int = 5
    max_correlation_cluster: int = 2


@dataclass(slots=True)
class Weights:
    st: dict[str, float] = field(default_factory=lambda: {
        "tsmom20": 0.22,
        "ols_t20": 0.20,
        "er20": 0.16,
        "donchian20": 0.18,
        "atr_pct": 0.10,
        "liquidity_penalty": 0.14,
    })
    lt: dict[str, float] = field(default_factory=lambda: {
        "tsmom126": 0.26,
        "price_vs_sma200": 0.18,
        "sma200_slope": 0.18,
        "ols_t90": 0.16,
        "drawdown_pressure": 0.10,
        "global_liquidity": 0.12,
    })
    mr: dict[str, float] = field(default_factory=lambda: {
        "z_close_20": 0.30,
        "boll_b": 0.20,
        "rsi2": 0.20,
        "residual_sma20": 0.20,
        "vr_gate": 0.10,
    })
