from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="TrendAtlas Crypto", layout="wide")

# =========================================================
# PATHS / CONFIG
# =========================================================

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
BTC_FILE = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"

FEEDBACK_DIR = ROOT / "feedback"
FEEDBACK_IMG_DIR = FEEDBACK_DIR / "images"
FEEDBACK_CSV = FEEDBACK_DIR / "feedback_log.csv"
MAX_UPLOAD_MB = 5
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

SELECTOR_PATH = OUTPUTS / "live_strategy_selector.json"

DEFAULT_SELECTOR = {
    "product_name": "TrendAtlas Crypto",
    "main_model_key": "phase67j_no_neo_main",
    "reference_model_key": "phase66g_production_soft_filters",
    "compare_model_keys": [
        "phase67j_no_neo_main",
        "phase66g_production_soft_filters",
    ],
    "display_names": {
        "phase67j_no_neo_main": {
            "sk": "Hlavná stratégia",
            "en": "Main strategy",
        },
        "phase66g_production_soft_filters": {
            "sk": "Referenčná stratégia",
            "en": "Reference strategy",
        },
    },
    "model_sources": {
        "phase67j_no_neo_main": {
            "summary_path": "outputs/phase67j_final_narrow_validation_pack/phase67j_final_narrow_validation_summary.csv",
            "paper_dir": "outputs/phase67j_final_narrow_validation_pack",
            "live_status_path": "outputs/phase67j_final_narrow_validation_pack/phase67j_live_status.csv",
        },
        "phase66g_production_soft_filters": {
            "summary_path": "outputs/phase66g_production_candidate_live/phase66g_production_candidate_summary.csv",
            "paper_dir": "outputs/phase66g_production_candidate_live",
            "live_status_path": "outputs/phase66g_production_candidate_live/phase66g_live_status.csv",
        },
    },
    "trend_barometer_source": {
        "live_status_path": "outputs/phase66g_production_candidate_live/phase66g_live_status.csv",
        "history_path": "outputs/phase66g_production_candidate_live/phase66g_trend_barometer_history.csv",
        "model_key": "phase66g_production_soft_filters",
    },
}

TEXT = {
    "sk": {
        "language": "Jazyk",
        "tabs": ["Domov", "Porovnanie", "Ako to funguje", "Feedback"],
        "hero": "Pravidlami riadená crypto rotačná stratégia pre meniace sa trhové podmienky",
        "subhero": (
            "TrendAtlas Crypto je navrhnutý pre ľudí, ktorí chcú disciplinovaný spôsob, ako sa pohybovať v crypto trhu "
            "bez toho, aby museli celý deň manuálne sledovať grafy. Systém pracuje s fixným shortlistom, priebežne hodnotí "
            "relatívnu silu kandidátov a drží iba tú pozíciu, ktorá momentálne najlepšie spĺňa jeho pravidlá."
        ),
        "home_title": "Dnes v skratke",
        "currently_holding": "Momentálne držíme",
        "trend_state": "Stav trendu",
        "trend_score": "Trend score",
        "buy_threshold": "Buy threshold",
        "trend_title": "Trend barometer",
        "trend_desc": "Toto je source-of-truth pohľad na stav trendu z core vrstvy. App nič nedopočítava, len zobrazuje exportovanú hodnotu.",
        "trend_threshold_note": "0.0 je core buy threshold. Nad nulou je trend nad hranou, pod nulou pod hranou. Governance vrstva ešte stále môže blokovať samotný buy.",
        "trend_history": "Mini história trend score",
        "trend_history_note": "Krivka ukazuje exportovanú históriu trend score. Biela čiara je buy threshold.",
        "trend_cross_none": "Bez dnešného prechodu",
        "na": "Nedostupné",
        "chart_title": "Vývoj kapitálu",
        "chart_note": "Graf ukazuje hlavnú stratégiu, referenčnú stratégiu a BTC Buy & Hold.",
        "chart_year": "Začať graf od roku",
        "performance_title": "Výkon na prvý pohľad",
        "ops_title": "Prevádzkové metriky",
        "total_return": "Celkové zhodnotenie",
        "cagr": "Priemerný ročný rast",
        "max_dd": "Najväčší pokles",
        "since2021": "Od 2021",
        "since2023": "Od 2023",
        "since2025": "Od 2025",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "switch_count": "Počet prepnutí",
        "cash_days": "Cash Days",
        "btc_days": "BTC Days",
        "latest_date": "Posledný uzavretý deň",
        "calc_title": "Koľko by bolo z 1 000 €",
        "calc_desc": "Vyber dátum a pozri sa, akú hodnotu by dnes mala modelová investícia 1 000 €.",
        "calc_date": "Dátum vkladu",
        "calc_used_date": "Použitý dátum",
        "calc_value": "Dnešná hodnota",
        "calc_return": "Zhodnotenie",
        "calc_note": "Je to modelový výpočet podľa equity krivky stratégie. Nie je to broker statement ani sľub budúceho výsledku.",
        "quick_examples": "Rýchle príklady",
        "overview_title": "Čo táto stratégia reálne robí",
        "overview_md": """
**Jednoducho povedané:**

Táto stratégia sa nesnaží držať desiatky coinov naraz.

Funguje ako rozhodovací systém, ktorý si opakovane kladie otázky:

1. Ktoré aktívum momentálne vyzerá najsilnejšie?
2. Je táto sila dosť kvalitná na to, aby sa podľa nej dalo konať?
3. Má ostať v aktuálnej pozícii, prepnúť do lepšej, alebo radšej ustúpiť?

V každom momente drží portfólio jednoducho:
- zvyčajne jednu aktívnu pozíciu naraz
- tou môže byť niektoré aktívum zo shortlistu
- a podľa širšieho setupu môže časť času tráviť aj v BTC alebo v cash-like defenzívnej pozícii
""",
        "compare_title": "Porovnanie stratégií",
        "compare_desc": "Porovnanie hlavnej stratégie, referenčnej stratégie a BTC Buy & Hold bez interných research názvov.",
        "compare_chart": "Porovnanie kapitálových kriviek",
        "compare_table": "Prehľad verzií",
        "method_title": "Ako to funguje",
        "method_md": """
### Základný princíp

- stratégia používa fixný shortlist
- vyberá len jednu aktívnu pozíciu naraz
- neprepína sa bezdôvodne, ale len vtedy, keď nový kandidát vyzerá dosť silno

### Čo je dôležité pre bežného používateľa

- systém sa snaží zachytiť silnejšie časti trhu
- keď podmienky nie sú dosť kvalitné, nemusí držať rizikovú pozíciu
- trend barometer ukazuje, ako ďaleko alebo blízko je trend k buy hranici
""",
        "feedback_title": "Feedback",
        "feedback_desc": "Pošli poznámku alebo screenshot. Obrázky majú limit 5 MB.",
        "feedback_text": "Tvoja správa",
        "feedback_placeholder": "Napíš, čo je jasné, nejasné, užitočné, pokazené alebo čo chýba...",
        "feedback_image": "Voliteľný obrázok",
        "feedback_send": "Uložiť feedback",
        "feedback_saved": "Feedback uložený.",
        "feedback_need_input": "Najprv napíš správu alebo pridaj obrázok.",
        "feedback_too_big": "Obrázok je príliš veľký. Maximum je 5 MB.",
        "feedback_failed": "Uloženie feedbacku zlyhalo",
        "feedback_files": "Ukladá sa do: feedback/feedback_log.csv a feedback/images/",
        "missing_files": "Chýbajú potrebné súbory:",
        "load_failed": "Načítanie dát zlyhalo",
        "btc_label": "BTC Buy & Hold",
        "cash": "CASH",
    },
    "en": {
        "language": "Language",
        "tabs": ["Home", "Comparison", "How it works", "Feedback"],
        "hero": "A rules-based crypto rotation strategy built for changing market conditions",
        "subhero": (
            "TrendAtlas Crypto is designed for people who want a disciplined way to navigate crypto without manually watching "
            "the market all day. The system works with a fixed shortlist, continuously evaluates relative strength, and holds "
            "only the position that currently fits its rules best."
        ),
        "home_title": "Today at a glance",
        "currently_holding": "Currently holding",
        "trend_state": "Trend state",
        "trend_score": "Trend score",
        "buy_threshold": "Buy threshold",
        "trend_title": "Trend barometer",
        "trend_desc": "This is a source-of-truth view of the trend state from the core layer. The app does not calculate the score itself.",
        "trend_threshold_note": "0.0 is the core buy threshold. Above zero means above the threshold, below zero means below it. Governance can still block actual buy execution.",
        "trend_history": "Mini trend score history",
        "trend_history_note": "The line shows exported trend score history. The white line is the buy threshold.",
        "trend_cross_none": "No cross today",
        "na": "Unavailable",
        "chart_title": "Capital curve",
        "chart_note": "The chart shows the main strategy, the reference strategy and BTC Buy & Hold.",
        "chart_year": "Start chart from year",
        "performance_title": "Performance at a glance",
        "ops_title": "Operational metrics",
        "total_return": "Total return",
        "cagr": "Average annual growth",
        "max_dd": "Largest decline",
        "since2021": "Since 2021",
        "since2023": "Since 2023",
        "since2025": "Since 2025",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "switch_count": "Switch count",
        "cash_days": "Cash Days",
        "btc_days": "BTC Days",
        "latest_date": "Last closed day",
        "calc_title": "What 1,000 € would have become",
        "calc_desc": "Choose a start date and see what a model-based 1,000 € investment would be worth today.",
        "calc_date": "Investment date",
        "calc_used_date": "Used date",
        "calc_value": "Value today",
        "calc_return": "Return",
        "calc_note": "This is a model-based calculation from the strategy equity curve. It is not a broker statement and not a promise of future results.",
        "quick_examples": "Quick examples",
        "overview_title": "What this strategy actually does",
        "overview_md": """
**In plain English:**

This strategy does not try to hold dozens of coins at once.

It works like a decision system that repeatedly asks:
1. Which asset currently looks strongest?
2. Is that strength strong enough to act on?
3. Should it stay, rotate, or stand aside?

At any point in time, the portfolio stays simple:
- usually one active position at a time
- that position can be a shortlisted asset
- and in weaker conditions the system can also spend time in BTC or a more defensive cash-like stance
""",
        "compare_title": "Strategy comparison",
        "compare_desc": "Comparison of the main strategy, the reference strategy and BTC Buy & Hold without internal research labels.",
        "compare_chart": "Capital curve comparison",
        "compare_table": "Version overview",
        "method_title": "How it works",
        "method_md": """
### Core idea

- the strategy uses a fixed shortlist
- it usually holds only one active position at a time
- it avoids unnecessary switching by requiring enough evidence before rotating

### What matters for a first-time visitor

- the system tries to capture stronger parts of the market
- when conditions are weak, it does not have to force risky exposure
- the trend barometer shows how far or close the trend is to the buy threshold
""",
        "feedback_title": "Feedback",
        "feedback_desc": "Send a comment or a screenshot. Images are limited to 5 MB.",
        "feedback_text": "Your message",
        "feedback_placeholder": "Tell us what feels clear, confusing, useful, broken, or missing...",
        "feedback_image": "Optional image",
        "feedback_send": "Save feedback",
        "feedback_saved": "Feedback saved.",
        "feedback_need_input": "Write a message or upload an image first.",
        "feedback_too_big": "The image is too large. Maximum is 5 MB.",
        "feedback_failed": "Saving feedback failed",
        "feedback_files": "Saved to: feedback/feedback_log.csv and feedback/images/",
        "missing_files": "Missing required files:",
        "load_failed": "Failed to load data",
        "btc_label": "BTC Buy & Hold",
        "cash": "CASH",
    },
}

METRIC_HELP = {
    "sk": {
        "Momentálne držíme": "Toto pole ide priamo z live CSV cez held_asset_public. App si ho sama nedopočítava.",
        "Stav trendu": "Textový stav exportovaný zo stratégie, nie vypočítaný v appke.",
        "Trend score": "Source-of-truth trend hodnota od -1 po +1. Pod nulou je trend pod buy hranou, nad nulou nad ňou.",
        "Buy threshold": "Hranica 0.0, ktorú používa core vrstva.",
        "Celkové zhodnotenie": "O koľko stratégia narástla za celé sledované obdobie.",
        "Priemerný ročný rast": "Vyhladené ročné tempo rastu. Praktickejšia metrika než len celkové zhodnotenie.",
        "Najväčší pokles": "Najhorší peak-to-trough prepad počas celej histórie.",
        "Od 2021": "Pohľad na výkon od roku 2021.",
        "Od 2023": "Pohľad na výkon v novšej trhovej ére.",
        "Od 2025": "Pohľad na výkon v úplne čerstvom období.",
        "Sharpe": "Pomer výnosu a volatility. Vyššie je zvyčajne lepšie.",
        "Sortino": "Podobné ako Sharpe, ale viac trestá negatívne výkyvy.",
        "Počet prepnutí": "Koľkokrát stratégia zmenila držanú pozíciu.",
        "Cash Days": "Koľko percent času stratégia radšej stála bokom.",
        "BTC Days": "Koľko percent času stratégia držala BTC.",
        "Posledný uzavretý deň": "Obchody vykonávame po uzavretí dňa, s jednodňovým oneskorením oproti signálu stratégie. Podľa testov je tento prístup stabilnejší a výnosnejší.",
    },
    "en": {
        "Currently holding": "This field is read directly from held_asset_public in the live CSV.",
        "Trend state": "Text state exported by the strategy layer.",
        "Trend score": "Source-of-truth trend value from -1 to +1.",
        "Buy threshold": "The 0.0 threshold used by the core layer.",
        "Total return": "How much the strategy grew over the full tracked period.",
        "Average annual growth": "Smoothed annual growth rate. More practical than only total return.",
        "Largest decline": "Worst peak-to-trough drawdown over the full history.",
        "Since 2021": "Performance view since 2021.",
        "Since 2023": "Performance view in the more recent market era.",
        "Since 2025": "Very recent performance window.",
        "Sharpe": "Return-to-volatility ratio. Higher is usually better.",
        "Sortino": "Similar to Sharpe, but punishes downside instability more.",
        "Switch count": "How many times the strategy changed the held position.",
        "Cash Days": "How often the strategy preferred to stay out of the market.",
        "BTC Days": "How often the strategy held BTC.",
        "Last closed day": "Trades are executed after the day closes, with a one-day delay versus the strategy signal. Based on our tests, this approach is more stable and more profitable.",
    },
}

# =========================================================
# HELPERS
# =========================================================

def normalize_path(value: str | Path | None) -> Path | None:
    if value is None or value == "":
        return None
    p = Path(value)
    if p.is_absolute():
        return p
    return ROOT / p


def as_float(value) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not str(value).strip()):
            return None
        v = float(value)
        if math.isnan(v):
            return None
        return v
    except Exception:
        return None


def maybe_pct_from_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return value * 100.0
    return value


def as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "áno", "ano"}:
        return True
    if text in {"false", "0", "no", "n", "nie"}:
        return False
    return None


def t(lang: str, key: str) -> str:
    return TEXT[lang][key]


def safe_metric_text(value, decimals: int = 2, suffix: str = "%", lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return f"{number:.{decimals}f}{suffix}"


def safe_int_text(value, lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return str(int(round(number)))


def safe_text_value(value, lang: str = "sk") -> str:
    if value is None:
        return t(lang, "na")
    text = str(value).strip()
    return text if text else t(lang, "na")


def prettify_trend_state(value: str | None, lang: str) -> str:
    if value is None:
        return t(lang, "na")
    raw = str(value).strip().lower()
    mapping = {
        "pod_buy_hranicou": {"sk": "Pod buy hranicou", "en": "Below buy threshold"},
        "nad_buy_hranicou": {"sk": "Nad buy hranicou", "en": "Above buy threshold"},
        "na_buy_hranici": {"sk": "Na buy hranici", "en": "At buy threshold"},
    }
    return mapping.get(raw, {"sk": str(value), "en": str(value)})[lang]


def prettify_asset_public(value: str | None, lang: str) -> str:
    if value is None:
        return t(lang, "na")
    raw = str(value).strip().upper()
    if raw in {"", "NONE"}:
        return t(lang, "na")
    if raw == "CASH":
        return t(lang, "cash")
    return raw


def trend_cross_text(trend_live: dict, lang: str) -> str:
    if trend_live.get("crossed_up_today") is True:
        return "Cross up today" if lang == "en" else "Dnes prechod hore"
    if trend_live.get("crossed_down_today") is True:
        return "Cross down today" if lang == "en" else "Dnes prechod dole"
    return t(lang, "trend_cross_none")


# =========================================================
# STYLING
# =========================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 1340px;
        }

        .hero-wrap {
            background:
                radial-gradient(circle at top left, rgba(17,138,178,0.17), transparent 35%),
                radial-gradient(circle at top right, rgba(165,110,255,0.17), transparent 35%),
                linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.012));
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 24px;
            padding: 1.2rem 1.25rem 1rem 1.25rem;
            margin-bottom: 1rem;
            box-shadow: 0 14px 42px rgba(0,0,0,0.28);
        }

        .gradient-line {
            height: 3px;
            width: 100%;
            background: linear-gradient(90deg, #ff6b6b, #ffd166, #06d6a0, #118ab2, #a56eff);
            border-radius: 999px;
            margin: 0.35rem 0 1rem 0;
        }

        .lang-wrap {
            margin-top: 0.55rem;
            margin-bottom: 0.95rem;
        }

        div[data-testid="stRadio"] > div {
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 999px;
            padding: 4px 10px;
            width: fit-content;
        }

        .card {
            border-radius: 18px;
            padding: 16px 18px;
            min-height: 118px;
            border: 1px solid rgba(255,255,255,0.09);
            box-shadow: 0 8px 28px rgba(0,0,0,0.18);
            margin-bottom: 10px;
        }

        .card-blue {
            background: linear-gradient(180deg, rgba(64,140,255,0.16), rgba(255,255,255,0.02));
        }

        .card-green {
            background: linear-gradient(180deg, rgba(6,214,160,0.16), rgba(255,255,255,0.02));
        }

        .card-violet {
            background: linear-gradient(180deg, rgba(165,110,255,0.16), rgba(255,255,255,0.02));
        }

        .card-orange {
            background: linear-gradient(180deg, rgba(255,161,90,0.16), rgba(255,255,255,0.02));
        }

        .card-neutral {
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.018));
        }

        .card-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
        }

        .card-label {
            font-size: 0.88rem;
            opacity: 0.82;
        }

        .card-info {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            background: rgba(255,255,255,0.10);
            color: #fff;
            border: 1px solid rgba(255,255,255,0.10);
            cursor: help;
        }

        .card-value {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.15;
            margin-bottom: 6px;
        }

        .card-sub {
            font-size: 0.92rem;
            opacity: 0.84;
        }

        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.018));
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 18px;
            padding: 8px 10px;
            box-shadow: 0 8px 28px rgba(0,0,0,0.18);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_color_card(label: str, value: str, subtitle: str = "", help_text: str | None = None, accent: str = "neutral") -> None:
    help_html = ""
    if help_text:
        safe_help = help_text.replace('"', "&quot;")
        help_html = f'<span class="card-info" title="{safe_help}">i</span>'

    st.markdown(
        f"""
        <div class="card card-{accent}">
            <div class="card-top">
                <div class="card-label">{label}</div>
                {help_html}
            </div>
            <div class="card-value">{value}</div>
            <div class="card-sub">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_box(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label=label, value=value, help=help_text, border=True)


# =========================================================
# DATA LOADING
# =========================================================

def build_display_map(selector: dict, lang: str) -> dict[str, str]:
    out: dict[str, str] = {}
    display_names = selector.get("display_names", {}) or {}
    for model_key, names in display_names.items():
        if isinstance(names, dict):
            out[model_key] = names.get(lang) or names.get("sk") or names.get("en") or model_key
        else:
            out[model_key] = str(names)
    return out


def human_label(model_key: str, lang: str, selector: dict) -> str:
    return build_display_map(selector, lang).get(model_key, model_key)


@st.cache_data(show_spinner=False)
def load_selector_config() -> dict:
    if SELECTOR_PATH.exists():
        with open(SELECTOR_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        merged = json.loads(json.dumps(DEFAULT_SELECTOR))
        merged.update(raw or {})
        merged["display_names"] = {
            **DEFAULT_SELECTOR.get("display_names", {}),
            **(raw or {}).get("display_names", {}),
        }
        merged["model_sources"] = {
            **DEFAULT_SELECTOR.get("model_sources", {}),
            **(raw or {}).get("model_sources", {}),
        }
        merged["trend_barometer_source"] = {
            **DEFAULT_SELECTOR.get("trend_barometer_source", {}),
            **(raw or {}).get("trend_barometer_source", {}),
        }
        return merged
    return json.loads(json.dumps(DEFAULT_SELECTOR))


@st.cache_data(show_spinner=False)
def load_csv_optional(path_str: str | None) -> pd.DataFrame:
    path = normalize_path(path_str)
    if path is None or not path.exists():
        return pd.DataFrame(columns=["model"])
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    if "model" not in df.columns:
        df["model"] = ""
    df["model"] = df["model"].astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def load_btc_df() -> pd.DataFrame:
    df = pd.read_csv(BTC_FILE)
    df = df.rename(
        columns={
            "Date": "date",
            "Timestamp": "timestamp",
            "Datetime": "datetime",
            "Time": "time",
            "Close": "close",
            "Open time": "open_time",
            "Open Time": "open_time",
        }
    )
    date_col = next((c for c in ["date", "timestamp", "datetime", "time", "open_time"] if c in df.columns), None)
    if date_col is None:
        raise ValueError("BTC file has no date column")
    if "close" not in df.columns:
        raise ValueError("BTC file has no close column")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=[date_col, "close"]).copy()
    df = df[[date_col, "close"]].rename(columns={date_col: "ts"}).sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    return df.drop_duplicates(subset=["ts"]).reset_index(drop=True)


def resolve_model_source(selector_cfg: dict, model_key: str) -> dict:
    model_sources = selector_cfg.get("model_sources", {}) or {}
    return dict(model_sources.get(model_key, {}) or {})


@st.cache_data(show_spinner=False)
def load_model_paper(paper_dir_str: str | None, model_key: str) -> pd.DataFrame:
    paper_dir = normalize_path(paper_dir_str)
    if paper_dir is None:
        raise FileNotFoundError("Paper dir is missing")

    candidates = [
        paper_dir / f"{model_key}_paper.csv",
        paper_dir / f"{model_key}.csv",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError(f"Missing paper file for model: {model_key}")

    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]

    if "date" not in df.columns:
        date_candidate = next((c for c in ["ts", "datetime", "timestamp", "Date"] if c in df.columns), None)
        if date_candidate is None:
            raise ValueError(f"{model_key} paper missing date column")
        df["date"] = df[date_candidate]

    if "equity" not in df.columns:
        eq_candidate = next((c for c in ["portfolio_value", "equity_curve", "nav"] if c in df.columns), None)
        if eq_candidate is None:
            raise ValueError(f"{model_key} paper missing equity column")
        df["equity"] = df[eq_candidate]

    df["ts"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    df = (
        df.dropna(subset=["ts", "equity"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    return df


def get_row(df: pd.DataFrame, model_key: str) -> pd.Series | None:
    if df.empty or "model" not in df.columns:
        return None
    row = df.loc[df["model"] == model_key]
    if row.empty:
        return None
    return row.iloc[0]


def get_metric_from_row(row: pd.Series | None, key: str) -> float | None:
    if row is None or key not in row.index:
        return None
    return as_float(row[key])


def get_text_from_row(row: pd.Series | None, key: str) -> str | None:
    if row is None or key not in row.index:
        return None
    value = row[key]
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None


# =========================================================
# METRICS / DERIVATIONS
# =========================================================

def calc_cagr_from_equity(df: pd.DataFrame, start_date: str | pd.Timestamp | None = None) -> float | None:
    if df.empty or "ts" not in df.columns or "equity" not in df.columns:
        return None
    work = df[["ts", "equity"]].copy()
    work["ts"] = pd.to_datetime(work["ts"], errors="coerce").dt.normalize()
    work["equity"] = pd.to_numeric(work["equity"], errors="coerce")
    work = work.dropna(subset=["ts", "equity"]).sort_values("ts")
    if start_date is not None:
        work = work[work["ts"] >= pd.Timestamp(start_date).normalize()].copy()
    if len(work) < 2:
        return None

    start_val = as_float(work["equity"].iloc[0])
    end_val = as_float(work["equity"].iloc[-1])
    if start_val is None or end_val is None or start_val <= 0 or end_val <= 0:
        return None

    days = (work["ts"].iloc[-1] - work["ts"].iloc[0]).days
    if days <= 0:
        return None

    years = days / 365.25
    if years <= 0:
        return None

    return ((end_val / start_val) ** (1.0 / years) - 1.0) * 100.0


def calc_total_return_from_equity(df: pd.DataFrame) -> float | None:
    if df.empty or "equity" not in df.columns:
        return None
    eq = pd.to_numeric(df["equity"], errors="coerce").dropna()
    if len(eq) < 2:
        return None
    start_val = as_float(eq.iloc[0])
    end_val = as_float(eq.iloc[-1])
    if start_val is None or end_val is None or start_val == 0:
        return None
    return (end_val / start_val - 1.0) * 100.0


def calc_max_drawdown_from_equity(df: pd.DataFrame) -> float | None:
    if df.empty or "equity" not in df.columns:
        return None
    eq = pd.to_numeric(df["equity"], errors="coerce").dropna()
    if eq.empty:
        return None
    peak = eq.cummax()
    dd = (eq / peak - 1.0) * 100.0
    return as_float(dd.min())


def derive_trade_count(df: pd.DataFrame) -> int | None:
    for col in ["selected_coin", "symbol", "asset", "holding", "position", "leader"]:
        if col in df.columns:
            s = df[col].astype(str).fillna("").tolist()
            if len(s) < 2:
                return 0
            changes = 0
            prev = s[0]
            for cur in s[1:]:
                if cur != prev:
                    changes += 1
                prev = cur
            return changes
    return None


def derive_cash_days_pct(df: pd.DataFrame) -> float | None:
    for col in ["selected_coin", "symbol", "asset", "holding", "position", "leader"]:
        if col in df.columns:
            s = df[col].astype(str).str.upper().fillna("")
            if s.empty:
                return None
            return as_float((s.isin(["CASH", "USD", "USDT", "USDC", "NONE"]).mean()) * 100.0)
    return None


def derive_btc_days_pct(df: pd.DataFrame) -> float | None:
    for col in ["selected_coin", "symbol", "asset", "holding", "position", "leader"]:
        if col in df.columns:
            s = df[col].astype(str).str.upper().fillna("")
            if s.empty:
                return None
            return as_float((s.str.contains("BTC", regex=False)).mean() * 100.0)
    return None


def build_metrics(summary_row: pd.Series | None, live_row: pd.Series | None, paper_df: pd.DataFrame) -> dict[str, float | int | str | None]:
    metrics: dict[str, float | int | str | None] = {}

    metrics["total_return_pct"] = get_metric_from_row(summary_row, "total_return_pct")
    if metrics["total_return_pct"] is None:
        metrics["total_return_pct"] = calc_total_return_from_equity(paper_df)

    metrics["cagr_pct"] = get_metric_from_row(summary_row, "cagr_pct")
    if metrics["cagr_pct"] is None:
        metrics["cagr_pct"] = calc_cagr_from_equity(paper_df)

    metrics["max_drawdown_pct"] = get_metric_from_row(summary_row, "max_drawdown_pct")
    if metrics["max_drawdown_pct"] is None:
        metrics["max_drawdown_pct"] = calc_max_drawdown_from_equity(paper_df)

    metrics["since2021_cagr_pct"] = get_metric_from_row(summary_row, "since2021_cagr_pct")
    if metrics["since2021_cagr_pct"] is None:
        metrics["since2021_cagr_pct"] = calc_cagr_from_equity(paper_df, "2021-01-01")

    metrics["since2023_cagr_pct"] = get_metric_from_row(summary_row, "since2023_cagr_pct")
    if metrics["since2023_cagr_pct"] is None:
        metrics["since2023_cagr_pct"] = calc_cagr_from_equity(paper_df, "2023-01-01")

    metrics["since2025_cagr_pct"] = get_metric_from_row(summary_row, "since2025_cagr_pct")
    if metrics["since2025_cagr_pct"] is None:
        metrics["since2025_cagr_pct"] = calc_cagr_from_equity(paper_df, "2025-01-01")

    metrics["switch_count"] = get_metric_from_row(summary_row, "switch_count")
    if metrics["switch_count"] is None:
        metrics["switch_count"] = get_metric_from_row(summary_row, "selection_count")
    if metrics["switch_count"] is None:
        metrics["switch_count"] = derive_trade_count(paper_df)

    metrics["cash_days_pct"] = get_metric_from_row(summary_row, "cash_days_pct")
    if metrics["cash_days_pct"] is None:
        metrics["cash_days_pct"] = derive_cash_days_pct(paper_df)

    raw_btc = get_metric_from_row(summary_row, "btc_days_pct")
    if raw_btc is None:
        raw_btc = get_metric_from_row(summary_row, "btc_days")
    metrics["btc_days_pct"] = maybe_pct_from_fraction(raw_btc)
    if metrics["btc_days_pct"] is None:
        metrics["btc_days_pct"] = derive_btc_days_pct(paper_df)

    if not paper_df.empty:
        metrics["latest_date"] = pd.to_datetime(paper_df["ts"].iloc[-1]).strftime("%Y-%m-%d")
    else:
        metrics["latest_date"] = None

    metrics["sharpe"] = get_metric_from_row(summary_row, "sharpe")
    metrics["sortino"] = get_metric_from_row(summary_row, "sortino")
    return metrics


def available_years_from_frames(frames: list[pd.DataFrame]) -> list[int]:
    years: set[int] = set()
    for df in frames:
        if "ts" in df.columns and not df.empty:
            vals = pd.to_datetime(df["ts"], errors="coerce").dropna().dt.year.tolist()
            years.update(int(x) for x in vals)
    return sorted(years)


def filter_from_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    out = df.copy()
    out["ts"] = pd.to_datetime(out["ts"], errors="coerce")
    return out[out["ts"].dt.year >= year].copy()


def rebase_series(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    first_valid = s.dropna()
    if first_valid.empty:
        return s
    return s / first_valid.iloc[0]


def nearest_valid_date(dates: pd.Series, picked_date) -> pd.Timestamp:
    picked = pd.Timestamp(picked_date).normalize()
    valid = pd.to_datetime(dates).dt.normalize().sort_values().drop_duplicates()
    valid = valid[valid >= picked]
    if valid.empty:
        return pd.to_datetime(dates).dt.normalize().max()
    return valid.iloc[0]


def investment_value(equity_df: pd.DataFrame, picked_date, amount: float = 1000.0) -> tuple[pd.Timestamp, float, float]:
    df = equity_df[["ts", "equity"]].copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    df = df.dropna().sort_values("ts")
    start_date = nearest_valid_date(df["ts"], picked_date)
    start_val = float(df.loc[df["ts"] == start_date, "equity"].iloc[0])
    end_val = float(df["equity"].iloc[-1])
    value_now = amount * (end_val / start_val)
    ret_pct = (value_now / amount - 1.0) * 100.0
    return start_date, value_now, ret_pct


# =========================================================
# LIVE STATE / TREND BAROMETER
# =========================================================

@st.cache_data(show_spinner=False)
def load_live_public_state(live_path: str | None, model_key: str, lang: str) -> dict:
    df = load_csv_optional(live_path)
    if df.empty:
        return {}

    row_df = df.loc[df["model"] == model_key] if "model" in df.columns else pd.DataFrame()
    row = row_df.iloc[0] if not row_df.empty else df.iloc[0]

    required_cols = [
        "held_asset_public",
        "held_state_label",
        "execution_state",
    ]
    has_new_fields = all(col in df.columns for col in required_cols)

    held_asset_public_raw = get_text_from_row(row, "held_asset_public") if has_new_fields else None
    held_state_label_raw = get_text_from_row(row, "held_state_label") if has_new_fields else None

    return {
        "has_new_fields": has_new_fields,
        "held_asset_public": prettify_asset_public(held_asset_public_raw, lang),
        "held_state_label": safe_text_value(held_state_label_raw, lang),
    }


@st.cache_data(show_spinner=False)
def load_trend_barometer_live(source_cfg: dict, lang: str) -> dict:
    df = load_csv_optional(source_cfg.get("live_status_path"))
    model_key = source_cfg.get("model_key")

    if df.empty:
        return {}

    if model_key and "model" in df.columns:
        row_df = df.loc[df["model"] == model_key]
        row = row_df.iloc[0] if not row_df.empty else df.iloc[0]
    else:
        row = df.iloc[0]

    return {
        "trend_score": as_float(row.get("trend_score")),
        "trend_state_label": prettify_trend_state(get_text_from_row(row, "trend_state_label"), lang),
        "buy_threshold": as_float(row.get("buy_threshold")),
        "crossed_up_today": as_bool(row.get("crossed_up_today")),
        "crossed_down_today": as_bool(row.get("crossed_down_today")),
        "trend_calc_date": get_text_from_row(row, "trend_calc_date"),
    }


@st.cache_data(show_spinner=False)
def load_trend_barometer_history(source_cfg: dict) -> pd.DataFrame:
    path = normalize_path(source_cfg.get("history_path"))
    if path is None or not path.exists():
        return pd.DataFrame(columns=["ts", "trend_score", "buy_threshold"])

    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]

    date_col = next((c for c in ["trend_calc_date", "date", "ts", "datetime", "timestamp"] if c in df.columns), None)
    if date_col is None or "trend_score" not in df.columns:
        return pd.DataFrame(columns=["ts", "trend_score", "buy_threshold"])

    df["ts"] = pd.to_datetime(df[date_col], errors="coerce")
    df["trend_score"] = pd.to_numeric(df["trend_score"], errors="coerce")
    if "buy_threshold" in df.columns:
        df["buy_threshold"] = pd.to_numeric(df["buy_threshold"], errors="coerce")
    else:
        df["buy_threshold"] = 0.0

    df = df.dropna(subset=["ts", "trend_score"]).sort_values("ts").reset_index(drop=True)
    return df[["ts", "trend_score", "buy_threshold"]]


# =========================================================
# CHARTS
# =========================================================

def make_capital_chart(
    main_df: pd.DataFrame,
    reference_df: pd.DataFrame | None,
    btc_df: pd.DataFrame,
    year: int,
    main_label: str,
    reference_label: str,
    btc_label: str,
    title: str,
) -> go.Figure:
    fig = go.Figure()

    if reference_df is not None and not reference_df.empty:
        ref_plot = filter_from_year(reference_df, year)
        fig.add_trace(
            go.Scatter(
                x=ref_plot["ts"],
                y=rebase_series(ref_plot["equity"]),
                mode="lines",
                name=reference_label,
                line=dict(width=2.0, color="#06d6a0", dash="dot"),
            )
        )

    btc_plot = filter_from_year(btc_df, year)
    fig.add_trace(
        go.Scatter(
            x=btc_plot["ts"],
            y=rebase_series(btc_plot["close"]),
            mode="lines",
            name=btc_label,
            line=dict(width=2.0, color="#7aa6ff"),
        )
    )

    main_plot = filter_from_year(main_df, year)
    fig.add_trace(
        go.Scatter(
            x=main_plot["ts"],
            y=rebase_series(main_plot["equity"]),
            mode="lines",
            name=main_label,
            line=dict(width=4.0, color="#ff6b6b"),
        )
    )

    fig.update_layout(
        height=540,
        title=title,
        template="plotly_dark",
        margin=dict(l=20, r=20, t=55, b=20),
        legend_title="",
        xaxis_title="",
        yaxis_title="Indexed growth",
        hovermode="x unified",
    )
    return fig


def make_trend_gauge(trend_live: dict, lang: str) -> go.Figure:
    score = trend_live.get("trend_score")
    threshold = trend_live.get("buy_threshold")
    value = score if score is not None else 0.0
    threshold_value = threshold if threshold is not None else 0.0
    bar_color = "#06d6a0" if value >= threshold_value else "#ff6b6b"

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"valueformat": ".4f"},
            title={"text": t(lang, "trend_score")},
            gauge={
                "axis": {"range": [-1, 1]},
                "bar": {"color": bar_color},
                "steps": [
                    {"range": [-1, -0.5], "color": "rgba(255,107,107,0.35)"},
                    {"range": [-0.5, 0], "color": "rgba(255,209,102,0.30)"},
                    {"range": [0, 0.5], "color": "rgba(6,214,160,0.22)"},
                    {"range": [0.5, 1], "color": "rgba(6,214,160,0.42)"},
                ],
                "threshold": {
                    "line": {"color": "#FFFFFF", "width": 4},
                    "thickness": 0.85,
                    "value": threshold_value,
                },
            },
        )
    )
    fig.update_layout(
        height=320,
        template="plotly_dark",
        margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


def make_trend_history_chart(history_df: pd.DataFrame, lang: str) -> go.Figure:
    fig = go.Figure()
    if not history_df.empty:
        fig.add_trace(
            go.Scatter(
                x=history_df["ts"],
                y=history_df["trend_score"],
                mode="lines",
                name=t(lang, "trend_score"),
                line=dict(width=2.5, color="#06d6a0"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=history_df["ts"],
                y=history_df["buy_threshold"],
                mode="lines",
                name=t(lang, "buy_threshold"),
                line=dict(width=2, color="#FFFFFF", dash="dash"),
            )
        )

    fig.update_layout(
        height=280,
        title=t(lang, "trend_history"),
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20),
        yaxis=dict(range=[-1.05, 1.05]),
        xaxis_title="",
        legend_title="",
    )
    return fig


# =========================================================
# FEEDBACK
# =========================================================

def ensure_feedback_dirs() -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    FEEDBACK_IMG_DIR.mkdir(parents=True, exist_ok=True)


def slugify_filename(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "_", name)
    return name[:80] if name else "file"


def save_feedback(note_text: str, uploaded_file) -> None:
    ensure_feedback_dirs()

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row_id = uuid.uuid4().hex[:12]
    image_path = ""
    original_name = ""

    if uploaded_file is not None:
        original_name = uploaded_file.name
        ext = Path(uploaded_file.name).suffix.lower()
        safe_name = slugify_filename(Path(uploaded_file.name).stem)
        final_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{row_id}_{safe_name}{ext}"
        target = FEEDBACK_IMG_DIR / final_name
        with open(target, "wb") as f:
            f.write(uploaded_file.getbuffer())
        image_path = str(target.relative_to(ROOT))

    row = pd.DataFrame(
        [{
            "created_utc": now,
            "id": row_id,
            "note_text": note_text.strip(),
            "image_original_name": original_name,
            "image_path": image_path,
        }]
    )

    if FEEDBACK_CSV.exists():
        existing = pd.read_csv(FEEDBACK_CSV)
        combined = pd.concat([existing, row], ignore_index=True)
    else:
        combined = row

    combined.to_csv(FEEDBACK_CSV, index=False)


# =========================================================
# APP
# =========================================================

inject_css()

if "lang" not in st.session_state:
    st.session_state.lang = "sk"

selector_cfg = load_selector_config()

hero_left, hero_right = st.columns([5, 1.6])

with hero_right:
    st.markdown('<div class="lang-wrap">', unsafe_allow_html=True)
    lang_choice = st.radio(
        label=t(st.session_state.lang, "language"),
        options=["SK", "EN"],
        index=0 if st.session_state.lang == "sk" else 1,
        horizontal=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

st.session_state.lang = "sk" if lang_choice == "SK" else "en"
lang = st.session_state.lang

with hero_left:
    st.markdown('<div class="hero-wrap">', unsafe_allow_html=True)
    st.title(selector_cfg.get("product_name") or "TrendAtlas Crypto")
    st.markdown('<div class="gradient-line"></div>', unsafe_allow_html=True)
    st.markdown(f"## {t(lang, 'hero')}")
    st.caption(t(lang, "subhero"))
    st.markdown("</div>", unsafe_allow_html=True)

required = [BTC_FILE]
missing = [str(p) for p in required if not p.exists()]
if missing:
    st.error(t(lang, "missing_files"))
    for path in missing:
        st.write(f"- {path}")
    st.stop()

main_key = selector_cfg.get("main_model_key")
reference_key = selector_cfg.get("reference_model_key")
compare_keys = [x for x in selector_cfg.get("compare_model_keys", []) if x]
labels = {key: human_label(key, lang, selector_cfg) for key in compare_keys}

try:
    btc_df = load_btc_df()
except Exception as e:
    st.error(f"{t(lang, 'load_failed')}: {e}")
    st.stop()

papers: dict[str, pd.DataFrame] = {}
model_metrics: dict[str, dict] = {}
paper_errors: list[str] = []

for model_key in compare_keys:
    source_cfg = resolve_model_source(selector_cfg, model_key)
    summary_df = load_csv_optional(source_cfg.get("summary_path"))
    live_df = load_csv_optional(source_cfg.get("live_status_path"))
    summary_row = get_row(summary_df, model_key)
    live_row = get_row(live_df, model_key)

    try:
        paper_df = load_model_paper(source_cfg.get("paper_dir"), model_key)
        papers[model_key] = paper_df
        model_metrics[model_key] = build_metrics(summary_row, live_row, paper_df)
    except Exception as e:
        paper_errors.append(f"{model_key}: {e}")

if main_key not in papers:
    st.error(f"{t(lang, 'load_failed')}: missing main model paper for {main_key}")
    for msg in paper_errors:
        st.write(f"- {msg}")
    st.stop()

main_source = resolve_model_source(selector_cfg, main_key)
live_public_state = load_live_public_state(main_source.get("live_status_path"), main_key, lang)

trend_source_cfg = selector_cfg.get("trend_barometer_source", {}) or {}
trend_live = load_trend_barometer_live(trend_source_cfg, lang)
trend_history_df = load_trend_barometer_history(trend_source_cfg)

main_metrics = model_metrics.get(main_key, {})
reference_metrics = model_metrics.get(reference_key, {})

years = available_years_from_frames(list(papers.values()) + [btc_df])
if not years:
    st.error(f"{t(lang, 'load_failed')}: no usable dates")
    st.stop()

main_equity_df = papers[main_key][["ts", "equity"]].dropna().copy()
reference_equity_df = papers.get(reference_key)

tabs = st.tabs(t(lang, "tabs"))

with tabs[0]:
    st.subheader(t(lang, "home_title"))

    home_cards = []

    if live_public_state.get("has_new_fields"):
        held_value = safe_text_value(live_public_state.get("held_asset_public"), lang=lang)
        if held_value != t(lang, "na"):
            home_cards.append(
                {
                    "label": t(lang, "currently_holding"),
                    "value": held_value,
                    "subtitle": "",
                    "help": METRIC_HELP[lang][t(lang, "currently_holding")],
                    "accent": "blue",
                }
            )

        home_cards.append(
        {
            "label": t(lang, "trend_state"),
            "value": safe_metric_text(trend_live.get("trend_score"), decimals=4, suffix="", lang=lang),
            "subtitle": safe_text_value(trend_live.get("trend_state_label"), lang=lang),
            "help": METRIC_HELP[lang][t(lang, "trend_score")],
            "accent": "orange",
        }
    )

    home_cols = st.columns(len(home_cards))
    for col, item in zip(home_cols, home_cards):
        with col:
            render_color_card(
                item["label"],
                item["value"],
                item["subtitle"],
                item["help"],
                item["accent"],
            )

    st.markdown(f"### {t(lang, 'chart_title')}")
    st.caption(t(lang, "chart_note"))
    selected_year_home = st.selectbox(
        t(lang, "chart_year"),
        options=years,
        index=0,
        key="selected_year_home",
    )
    st.plotly_chart(
        make_capital_chart(
            main_df=papers[main_key],
            reference_df=reference_equity_df,
            btc_df=btc_df,
            year=selected_year_home,
            main_label=labels.get(main_key, main_key),
            reference_label=labels.get(reference_key, reference_key),
            btc_label=t(lang, "btc_label"),
            title=t(lang, "chart_title"),
        ),
        use_container_width=True,
    )

    st.markdown(f"### {t(lang, 'performance_title')}")
    perf1 = st.columns(3)
    with perf1[0]:
        render_color_card(t(lang, "cagr"), safe_metric_text(main_metrics.get("cagr_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "cagr")], "blue")
    with perf1[1]:
        render_color_card(t(lang, "since2023"), safe_metric_text(main_metrics.get("since2023_cagr_pct"), lang=lang), "CAGR", METRIC_HELP[lang][t(lang, "since2023")], "green")
    with perf1[2]:
        render_color_card(t(lang, "since2025"), safe_metric_text(main_metrics.get("since2025_cagr_pct"), lang=lang), "CAGR", METRIC_HELP[lang][t(lang, "since2025")], "violet")

    perf2 = st.columns(3)
    with perf2[0]:
        render_color_card(t(lang, "max_dd"), safe_metric_text(main_metrics.get("max_drawdown_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "max_dd")], "orange")
    with perf2[1]:
        render_color_card(t(lang, "sharpe"), safe_metric_text(main_metrics.get("sharpe"), decimals=3, suffix="", lang=lang), "", METRIC_HELP[lang][t(lang, "sharpe")], "neutral")
    with perf2[2]:
        render_color_card(t(lang, "sortino"), safe_metric_text(main_metrics.get("sortino"), decimals=3, suffix="", lang=lang), "", METRIC_HELP[lang][t(lang, "sortino")], "neutral")

    st.markdown(f"### {t(lang, 'trend_title')}")
    st.caption(t(lang, "trend_desc"))

    trend_cols = st.columns([1.35, 1.65])
    with trend_cols[0]:
        st.plotly_chart(make_trend_gauge(trend_live, lang), use_container_width=True)

    with trend_cols[1]:
        tc1 = st.columns(2)
        with tc1[0]:
            render_color_card(
                t(lang, "trend_state"),
                safe_text_value(trend_live.get("trend_state_label"), lang=lang),
                "",
                METRIC_HELP[lang][t(lang, "trend_state")],
                "orange",
            )
        with tc1[1]:
            render_color_card(
                t(lang, "buy_threshold"),
                safe_metric_text(trend_live.get("buy_threshold"), decimals=4, suffix="", lang=lang),
                trend_cross_text(trend_live, lang),
                METRIC_HELP[lang][t(lang, "buy_threshold")],
                "violet",
            )

        st.caption(t(lang, "trend_threshold_note"))
        if trend_live.get("trend_calc_date"):
            st.caption(f"Calc date: {trend_live.get('trend_calc_date')}")

    if not trend_history_df.empty:
        st.plotly_chart(make_trend_history_chart(trend_history_df, lang), use_container_width=True)
        st.caption(t(lang, "trend_history_note"))

    st.markdown(f"### {t(lang, 'ops_title')}")
    ops = st.columns(5)
    with ops[0]:
        render_color_card(t(lang, "total_return"), safe_metric_text(main_metrics.get("total_return_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "total_return")], "blue")
    with ops[1]:
        render_color_card(t(lang, "switch_count"), safe_int_text(main_metrics.get("switch_count"), lang=lang), "", METRIC_HELP[lang][t(lang, "switch_count")], "neutral")
    with ops[2]:
        render_color_card(t(lang, "cash_days"), safe_metric_text(main_metrics.get("cash_days_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "cash_days")], "green")
    with ops[3]:
        render_color_card(t(lang, "btc_days"), safe_metric_text(main_metrics.get("btc_days_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "btc_days")], "violet")
    with ops[4]:
        render_color_card(t(lang, "latest_date"), safe_text_value(main_metrics.get("latest_date"), lang=lang), "", METRIC_HELP[lang][t(lang, "latest_date")], "neutral")

    st.markdown(f"### {t(lang, 'calc_title')}")
    st.write(t(lang, "calc_desc"))

    available_dates = pd.to_datetime(main_equity_df["ts"]).dt.normalize().sort_values().drop_duplicates()
    default_date = nearest_valid_date(available_dates, pd.Timestamp("2024-01-01"))
    picked_date = st.date_input(
        t(lang, "calc_date"),
        value=default_date.date(),
        min_value=available_dates.min().date(),
        max_value=available_dates.max().date(),
    )

    used_date, value_now, ret_pct = investment_value(main_equity_df, picked_date, amount=1000.0)

    calc_df = pd.DataFrame(
        [
            {
                t(lang, "calc_used_date"): used_date.strftime("%Y-%m-%d"),
                t(lang, "calc_value"): f"{value_now:,.2f} €",
                t(lang, "calc_return"): f"{ret_pct:+.2f}%",
            }
        ]
    )
    st.dataframe(calc_df, use_container_width=True, hide_index=True)
    st.caption(t(lang, "calc_note"))

    example_rows = []
    example_points = [
        available_dates.min(),
        pd.Timestamp("2021-01-01"),
        pd.Timestamp("2023-01-01"),
        pd.Timestamp("2025-01-01"),
    ]
    seen = set()
    for point in example_points:
        dt = nearest_valid_date(available_dates, point)
        if dt in seen:
            continue
        seen.add(dt)
        e_used, e_value, e_ret = investment_value(main_equity_df, dt, amount=1000.0)
        example_rows.append(
            {
                "Dátum" if lang == "sk" else "Date": e_used.strftime("%Y-%m-%d"),
                "Hodnota" if lang == "sk" else "Value": f"{e_value:,.2f} €",
                "Zhodnotenie" if lang == "sk" else "Return": f"{e_ret:+.2f}%",
            }
        )

    st.markdown(f"#### {t(lang, 'quick_examples')}")
    st.dataframe(pd.DataFrame(example_rows), use_container_width=True, hide_index=True)

    st.markdown(f"### {t(lang, 'overview_title')}")
    st.markdown(t(lang, "overview_md"))

    if paper_errors:
        st.warning(" / ".join(paper_errors))

with tabs[1]:
    st.subheader(t(lang, "compare_title"))
    st.caption(t(lang, "compare_desc"))

    selected_year_compare = st.selectbox(
        t(lang, "chart_year"),
        options=years,
        index=0,
        key="selected_year_compare",
    )
    st.plotly_chart(
        make_capital_chart(
            main_df=papers[main_key],
            reference_df=reference_equity_df,
            btc_df=btc_df,
            year=selected_year_compare,
            main_label=labels.get(main_key, main_key),
            reference_label=labels.get(reference_key, reference_key),
            btc_label=t(lang, "btc_label"),
            title=t(lang, "compare_chart"),
        ),
        use_container_width=True,
    )

    compare_df = pd.DataFrame(
        [
            {
                "Stratégia" if lang == "sk" else "Strategy": labels.get(main_key, main_key),
                t(lang, "cagr"): safe_metric_text(main_metrics.get("cagr_pct"), lang=lang),
                t(lang, "max_dd"): safe_metric_text(main_metrics.get("max_drawdown_pct"), lang=lang),
                t(lang, "since2023"): safe_metric_text(main_metrics.get("since2023_cagr_pct"), lang=lang),
                t(lang, "since2025"): safe_metric_text(main_metrics.get("since2025_cagr_pct"), lang=lang),
                t(lang, "sharpe"): safe_metric_text(main_metrics.get("sharpe"), decimals=3, suffix="", lang=lang),
                t(lang, "sortino"): safe_metric_text(main_metrics.get("sortino"), decimals=3, suffix="", lang=lang),
            },
            {
                "Stratégia" if lang == "sk" else "Strategy": labels.get(reference_key, reference_key),
                t(lang, "cagr"): safe_metric_text(reference_metrics.get("cagr_pct"), lang=lang),
                t(lang, "max_dd"): safe_metric_text(reference_metrics.get("max_drawdown_pct"), lang=lang),
                t(lang, "since2023"): safe_metric_text(reference_metrics.get("since2023_cagr_pct"), lang=lang),
                t(lang, "since2025"): safe_metric_text(reference_metrics.get("since2025_cagr_pct"), lang=lang),
                t(lang, "sharpe"): safe_metric_text(reference_metrics.get("sharpe"), decimals=3, suffix="", lang=lang),
                t(lang, "sortino"): safe_metric_text(reference_metrics.get("sortino"), decimals=3, suffix="", lang=lang),
            },
        ]
    )
    st.markdown(f"### {t(lang, 'compare_table')}")
    st.dataframe(compare_df, use_container_width=True, height=190, hide_index=True)

with tabs[2]:
    st.subheader(t(lang, "method_title"))
    st.markdown(t(lang, "method_md"))

with tabs[3]:
    st.subheader(t(lang, "feedback_title"))
    st.caption(t(lang, "feedback_desc"))

    with st.form("feedback_form", clear_on_submit=True):
        note_text = st.text_area(
            t(lang, "feedback_text"),
            placeholder=t(lang, "feedback_placeholder"),
            height=180,
        )
        uploaded_file = st.file_uploader(
            t(lang, "feedback_image"),
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=False,
        )
        submitted = st.form_submit_button(t(lang, "feedback_send"))

    if submitted:
        if not note_text.strip() and uploaded_file is None:
            st.warning(t(lang, "feedback_need_input"))
        elif uploaded_file is not None and getattr(uploaded_file, "size", 0) > MAX_UPLOAD_BYTES:
            st.warning(t(lang, "feedback_too_big"))
        else:
            try:
                ensure_feedback_dirs()

                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                row_id = uuid.uuid4().hex[:12]
                image_path = ""
                original_name = ""

                if uploaded_file is not None:
                    original_name = uploaded_file.name
                    ext = Path(uploaded_file.name).suffix.lower()
                    safe_name = re.sub(r"[^a-z0-9._-]+", "_", Path(uploaded_file.name).stem.strip().lower())[:80] or "file"
                    final_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{row_id}_{safe_name}{ext}"
                    target = FEEDBACK_IMG_DIR / final_name
                    with open(target, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    image_path = str(target.relative_to(ROOT))

                row = pd.DataFrame(
                    [{
                        "created_utc": now,
                        "id": row_id,
                        "note_text": note_text.strip(),
                        "image_original_name": original_name,
                        "image_path": image_path,
                    }]
                )

                if FEEDBACK_CSV.exists():
                    existing = pd.read_csv(FEEDBACK_CSV)
                    combined = pd.concat([existing, row], ignore_index=True)
                else:
                    combined = row

                combined.to_csv(FEEDBACK_CSV, index=False)
                st.success(t(lang, "feedback_saved"))
            except Exception as e:
                st.error(f"{t(lang, 'feedback_failed')}: {e}")

    st.caption(t(lang, "feedback_files"))