from __future__ import annotations

import html
import hmac
import csv
import json
import math
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
import sys
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
)
from scripts.execution.trading_operation_mode import (
    DEFAULT_TRADING_OPERATION_MODE_PATH,
)
from scripts.production.data_health_common import (
    REPORT_ARTIFACT_TYPE,
    build_report_bundle,
    informational_warning_sources,
    research_warning_sources,
)

APP_EXECUTE_BRIDGE_IMPORT_ERROR = ""
try:
    from scripts.execution.app_execute_bridge import (
        BACKEND_CONFIRM_TOKEN as APP_BACKEND_CONFIRM_TOKEN,
        UI_CONFIRMATION_TEXT as APP_UI_CONFIRMATION_TEXT,
        run_app_execute_action,
    )
except Exception as exc:  # pragma: no cover - Streamlit fallback only
    APP_BACKEND_CONFIRM_TOKEN = "CONTROLLED_REAL_ORDER"
    APP_UI_CONFIRMATION_TEXT = "POTVRDZUJEM VYKONAT OBCHOD"
    run_app_execute_action = None
    APP_EXECUTE_BRIDGE_IMPORT_ERROR = str(exc)

st.set_page_config(page_title="TrendAtlas Crypto", layout="wide")

# =========================================================
# PATHS / CONFIG
# =========================================================

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
PRODUCTION_OUTPUTS = OUTPUTS / "production"
AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH = (
    ROOT / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
)
AUTHORITY_LATEST_ATTEMPT_STATUS_PATH = (
    ROOT / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
)
LOCAL_APP_RUNTIME_SNAPSHOT_PATH = (
    ROOT / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json"
)
LOCAL_DASHBOARD_PUBLIC_STATUS_PATH = (
    ROOT / "outputs" / "execution" / "app_snapshot" / "dashboard_public_status.json"
)
LOCAL_DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH = (
    ROOT / "outputs" / "execution" / "app_snapshot" / "dashboard_public_chart_timeseries.csv"
)
PRODUCTION_SNAPSHOT_PATH = PRODUCTION_OUTPUTS / "current_strategy_snapshot.json"
PRODUCTION_TIMESERIES_PATH = PRODUCTION_OUTPUTS / "current_strategy_timeseries.csv"
PRODUCTION_DIAGNOSTICS_PATH = PRODUCTION_OUTPUTS / "current_strategy_diagnostics.json"
PRODUCTION_QUALITY_PATH = PRODUCTION_OUTPUTS / "current_strategy_snapshot.quality.json"
DATA_HEALTH_REPORT_PATH = PRODUCTION_OUTPUTS / "data_health_report.json"
TRADING_OPERATION_MODE_CONFIG_PATH = DEFAULT_TRADING_OPERATION_MODE_PATH
LIVE_ORDER_CONFIRMATION_TEXT = "POTVRDZUJEM"
APP_DISPLAY_TIMEZONE = ZoneInfo("Europe/Bratislava")
ETF_FLOW_PUBLIC_STRATEGY_VERSION = "phase68g_etf_flow_impulse_early_risk_cooldown_15"
ETF_FLOW_PUBLIC_EVIDENCE_START_DATE = "2024-01-12"
BTC_REALTIME_TICKER_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
)

CONTACT_DIR = ROOT / "contact"
CONTACT_CSV = CONTACT_DIR / "contact_log.csv"

APP_SELECTOR_DEFAULTS = {
    "product_name": "TrendAtlas Crypto",
}

TEXT = {
    "sk": {
        "language": "Jazyk",
        "tabs": ["Domov", "Účet", "Ako to funguje", "Kontakt"],
        "hero": "Pravidlami riadená crypto rotačná stratégia pre meniace sa trhové podmienky",
        "subhero": (
            "TrendAtlas Crypto je navrhnutý pre ľudí, ktorí chcú disciplinovaný spôsob, ako sa pohybovať v crypto trhu "
            "bez toho, aby museli celý deň manuálne sledovať grafy. Systém pracuje s fixným shortlistom, priebežne hodnotí "
            "relatívnu silu kandidátov a drží iba tú pozíciu, ktorá momentálne najlepšie spĺňa jeho pravidlá."
        ),
        "home_title": "Prehľad",
        "currently_holding": "Modelová pozícia",
        "trend_state": "Stav trendu",
        "trend_score": "Trend score",
        "buy_threshold": "Buy threshold",
        "live_mode": "Live režim",
        "current_profile": "Aktuálny profil",
        "fallback_profile": "Fallback profil",
        "trend_title": "Trend barometer",
        "trend_desc": "Toto je source-of-truth pohľad na stav trendu z core vrstvy. App nič nedopočítava, len zobrazuje exportovanú hodnotu.",
        "trend_threshold_note": "0.0 je core buy threshold. Nad nulou je trend nad hranou, pod nulou pod hranou. Governance vrstva ešte stále môže blokovať samotný buy.",
        "trend_history": "Mini história trend score",
        "trend_history_note": "Krivka ukazuje exportovanú históriu trend score. Biela čiara je buy threshold.",
        "trend_cross_none": "Bez prechodu k dátumu výpočtu",
        "na": "Nedostupné",
        "chart_title": "Vývoj kapitálu",
        "chart_note": "Horná krivka ukazuje výkon hlavného modelu proti BTC benchmarku. Spodný pás ukazuje, čo stratégia reálne držala v čase.",
        "chart_regime_strip_note": "Rovné úseky počas stavu CASH znamenajú, že model stál mimo trhu. Nejde o zaseknutý ani chýbajúci graf.",
        "chart_current_regime_label": "Aktuálny režim",
        "chart_current_regime_cash": "CASH / bez trhovej expozície. Rovnejšie úseky sú v tomto stave očakávané.",
        "chart_current_regime_exposed": "Expozícia v aktíve {asset}.",
        "chart_visible_cash_explainer": "Rovné úseky počas stavu CASH znamenajú, že model stál mimo trhu. Nejde o zaseknutý ani chýbajúci graf.",
        "chart_visible_state_explainer": "Spodný pás ukazuje, čo model reálne držal. Koniec aktuálne viditeľného grafu je v režime {regime}.",
        "chart_year": "Začať graf od roku",
        "chart_performance_axis": "Indexovaný rast",
        "chart_state_axis": "Držaný stav",
        "chart_state_cash": "CASH",
        "chart_state_base": "CASH",
        "chart_state_btc": "BTC",
        "chart_state_alt": "ALT",
        "chart_state_period": "Držané",
        "performance_title": "Výkon na prvý pohľad",
        "performance_fee_note": "Výsledky sú už po započítaní poplatkov Hyperliquid.",
        "ops_title": "Prevádzkové metriky",
        "total_return": "Celkové zhodnotenie",
        "cagr": "Priemerný ročný rast",
        "max_dd": "Najväčší pokles",
        "since2021": "Od 2021",
        "since2023": "Od 2023",
        "since_etf_start": "Od ETF štartu",
        "since2025": "Od 2025",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "switch_count": "Počet prepnutí",
        "cash_days": "Cash Days",
        "btc_days": "BTC Days",
        "strategy_last_update": "Dátum dát stratégie",
        "calc_title": "Koľko by bolo z 1 000 €",
        "calc_desc": "Vyber dátum a pozri sa, akú hodnotu by mala modelová investícia 1 000 EUR podľa posledných dostupných dát.",
        "calc_date": "Dátum vkladu",
        "calc_used_date": "Použitý dátum",
        "calc_value": "Modelová hodnota",
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
### Ako stratégia funguje

Táto stratégia je postavená na riadenej rotácii podľa trhového režimu.  
Jej úloha je jednoduchá: **držať jednu najsilnejšiu pozíciu alebo zostať v hotovosti**.

Nesnaží sa predpovedať každý krátkodobý pohyb trhu.  
Namiesto toho si priebežne kladie dve hlavné otázky:

- Je trh v dostatočne zdravom stave na to, aby malo zmysel niesť riziko?
- Ak áno, ktoré jediné aktívum má momentálne najlepšie predpoklady na držanie?

### Základná logika

Stratégia sa začína od základného signálu trhového režimu.  
Ten vyhodnocuje, či je celkové prostredie dostatočne silné na risk-on prístup. Ak nie je, systém zostáva opatrný a preferuje hotovosť.

Ak sú podmienky vhodné, stratégia následne porovnáva kandidátske aktíva a vytvára pre ne skóre na základe viacerých faktorov, najmä trendu, sily výnosov, rizika a volatility.  
Do finálneho výberu sa dostanú len tie aktíva, ktoré prejdú kvalitatívnymi a bezpečnostnými filtrami.

### Rozhodovanie o držaní a prepínaní

Nestačí len to, že je nejaké aktívum na prvom mieste.  
Stratégia zároveň rieši aj to, **či sa vôbec oplatí meniť aktuálnu pozíciu**.

Preto používa riadiacu vrstvu, ktorá:

- porovnáva aktuálne držané aktívum s novými kandidátmi
- vyžaduje dostatočne silnú výhodu pred prepnutím
- bráni zbytočne častému prehadzovaniu pozícií
- využíva ochranné pravidlá typu minimum hold time, probation a cooldown

Práve toto je dôležité, pretože veľa stratégií vyzerá dobre na papieri, ale v praxi zlyháva na príliš častých zmenách, slabých vstupoch alebo nestabilnom vedení.

### Čo môže stratégia držať

V každom momente môže byť stratégia len v jednom z týchto stavov:

- **Cash**, ak podmienky nie sú dostatočne kvalitné
- **BTC**, ak je Bitcoin najsilnejšia validná voľba
- **jeden vybraný altcoin**, ak si jasne zaslúži nahradiť aktuálne držanú pozíciu

V praxi teda ide o **top-1 rotačný systém s možnosťou zostať v hotovosti**.

### Prečo stratégia niekedy zostáva v hotovosti

Hotovosť neznamená, že systém „nič nerobí“.  
Znamená to, že trh ešte neprekročil kvalitatívnu hranicu pre nákup, alebo modelová voľba nie je dosť presvedčivá na reálnu expozíciu.

Aj preto môže model preferovať lídra, ale obchod ešte nespustiť.
Modelová voľba môže existovať, no bezpečnostná a riadiaca vrstva stále nemusí dovoliť vstup.

### Čím je táto stratégia iná

Dôležité je, že toto nie je len jednoduchý ranking model.  
Stratégia stojí na troch vrstvách:

- **Filter trhového režimu** – rozhoduje, či má byť riziko vôbec zapnuté
- **Vrstva výberu aktíva** – hľadá najsilnejšie validné aktívum
- **Riadiaca vrstva** – rozhoduje, či je zmena pozície naozaj opodstatnená

Práve tretia vrstva robí veľký rozdiel medzi modelom, ktorý vyzerá dobre len v backteste, a modelom, ktorý sa správa disciplinovane aj v reálnej prevádzke.

### Praktické správanie stratégie

V praxi sa stratégia správa veľmi jednoducho:

- zostáva v hotovosti, keď trhové podmienky nie sú dosť dobré
- inak drží jedno najsilnejšie validné aktívum
- neprepína bez dostatočne jasnej výhody
- snaží sa vyhýbať hlučným a nekvalitným zmenám

### Prečo používame uzavretý deň

Obchody vykonávame po uzavretí dňa, s jednodňovým oneskorením oproti signálu stratégie.  
Podľa testov je tento prístup stabilnejší a výnosnejší.
""",
        "contact_title": "Kontakt",
        "contact_desc": "Ak ťa stratégia zaujala, chceš spoluprácu alebo sa chceš niečo opýtať, nechaj tu email a krátku správu. Ozvem sa len na relevantné veci.",
        "contact_email": "Email",
        "contact_type": "Typ správy",
        "contact_message": "Správa",
        "contact_placeholder": "Napíš stručne, čo chceš, čo ťa zaujíma alebo s čím chceš pomôcť...",
        "contact_send": "Uložiť správu",
        "contact_saved": "Správa uložená.",
        "contact_need_input": "Vyplň email aj správu.",
        "contact_bad_email": "Zadaj platný email.",
        "contact_failed": "Uloženie správy zlyhalo",
        "contact_files": "Ukladá sa do: contact/contact_log.csv",
        "contact_type_options": ["Otázka", "Záujem o produkt", "Partnerstvo", "Bug / problém", "Iné"],
        "missing_files": "Chýbajú potrebné súbory:",
        "load_failed": "Načítanie dát zlyhalo",
        "account_title": "Účet",
        "account_snapshot_note": "Read-only snapshot burzového účtu. Ide o prevádzkový prehľad, nie oficiálny stav stratégie.",
        "account_connection": "Stav pripojenia",
        "account_last_sync": "Posledná synchronizácia",
        "account_total_value": "Celková hodnota účtu",
        "account_available_balance": "Dostupný zostatok",
        "account_open_position": "Otvorená pozícia",
        "account_open_orders": "Otvorené príkazy",
        "account_recent_fills": "Nedávne obchody",
        "account_provider": "Provider",
        "account_address": "Adresa účtu",
        "account_copy_address": "Kopírovať plnú adresu",
        "account_last_action": "Posledné vyhodnotenie",
        "account_last_result": "Záver",
        "account_position_details": "Detail pozície",
        "account_no_position": "Žiadna otvorená pozícia",
        "account_position_empty_note": "Na účte momentálne nie je otvorená žiadna pozícia.",
        "account_symbol": "Symbol",
        "account_side": "Smer",
        "account_size": "Veľkosť",
        "account_entry_price": "Entry cena",
        "account_mark_price": "Mark cena",
        "account_unrealized_pnl_usd": "Unrealized PnL USD",
        "account_unrealized_pnl_pct": "Unrealized PnL %",
        "account_long": "Long",
        "account_short": "Short",
        "account_status_ok": "OK",
        "account_status_unavailable": "Nedostupné",
        "btc_label": "BTC Buy & Hold",
        "cash": "CASH",
    },
    "en": {
        "language": "Language",
        "tabs": ["Home", "Account", "How it works", "Contact"],
        "hero": "A rules-based crypto rotation strategy built for changing market conditions",
        "subhero": (
            "TrendAtlas Crypto is designed for people who want a disciplined way to navigate crypto without manually watching "
            "the market all day. The system works with a fixed shortlist, continuously evaluates relative strength, and holds "
            "only the position that currently fits its rules best."
        ),
        "home_title": "Overview",
        "currently_holding": "Model position",
        "trend_state": "Trend state",
        "trend_score": "Trend score",
        "buy_threshold": "Buy threshold",
        "live_mode": "Live režim",
        "current_profile": "Aktuálny profil",
        "fallback_profile": "Fallback profil",
        "trend_title": "Trend barometer",
        "trend_desc": "This is a source-of-truth view of the trend state from the core layer. The app does not calculate the score itself.",
        "trend_threshold_note": "0.0 is the core buy threshold. Above zero means above the threshold, below zero means below it. Governance can still block actual buy execution.",
        "trend_history": "Mini trend score history",
        "trend_history_note": "The line shows exported trend score history. The white line is the buy threshold.",
        "trend_cross_none": "No cross on calc date",
        "na": "Unavailable",
        "chart_title": "Capital curve",
        "chart_note": "The top line shows the main model versus the BTC benchmark. The lower strip shows what the strategy was actually holding through time.",
        "chart_regime_strip_note": "Flat sections during CASH mean the model stayed out of the market. This is intentional, not broken chart data.",
        "chart_current_regime_label": "Current regime",
        "chart_current_regime_cash": "CASH / no market exposure. Flatter sections are expected in this state.",
        "chart_current_regime_exposed": "{asset} exposure.",
        "chart_visible_cash_explainer": "Flat sections during CASH mean the model was out of the market. The chart is not stuck or missing.",
        "chart_visible_state_explainer": "The lower strip shows what the model was actually holding. The visible end of the chart is currently in regime {regime}.",
        "chart_year": "Start chart from year",
        "chart_performance_axis": "Indexed growth",
        "chart_state_axis": "Held state",
        "chart_state_cash": "CASH",
        "chart_state_base": "CASH",
        "chart_state_btc": "BTC",
        "chart_state_alt": "ALT",
        "chart_state_period": "Held",
        "performance_title": "Performance at a glance",
        "performance_fee_note": "Results already include Hyperliquid fees.",
        "ops_title": "Operational metrics",
        "total_return": "Total return",
        "cagr": "Average annual growth",
        "max_dd": "Largest decline",
        "since2021": "Since 2021",
        "since2023": "Since 2023",
        "since_etf_start": "Since ETF start",
        "since2025": "Since 2025",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "switch_count": "Switch count",
        "cash_days": "Cash Days",
        "btc_days": "BTC Days",
        "strategy_last_update": "Strategy data date",
        "calc_title": "What 1,000 € would have become",
        "calc_desc": "Choose a start date and see the value of a model-based EUR 1,000 investment using the latest available data.",
        "calc_date": "Investment date",
        "calc_used_date": "Used date",
        "calc_value": "Model value",
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
        "compare_desc": "Comparison of the main strategy, the reference strategy and BTC Buy & Hold using public names.",
        "compare_chart": "Capital curve comparison",
        "compare_table": "Version overview",
        "method_title": "How it works",
        "method_md": """
### How the strategy works

This strategy is built around regime-based rotation.  
Its job is simple: **hold the single strongest position or stay in cash**.

It does not try to predict every short-term market move.  
Instead, it keeps answering two main questions:

- Is the market healthy enough to justify taking risk?
- If yes, which single asset is currently the best one to hold?

### Core logic

The strategy starts with a baseline market regime signal.  
That signal evaluates whether the overall environment is strong enough for risk-on positioning. If it is not, the system stays defensive and prefers cash.

If conditions are strong enough, the strategy then evaluates the shortlisted assets and scores them using multiple inputs, especially trend, return strength, risk, and volatility.
Only assets that pass the required quality and safety filters are allowed to compete.

### Holding and switching logic

It is not enough for an asset to rank first.  
The strategy also decides **whether switching is actually worth it**.

That is why it includes a governance layer that:

- compares the currently held asset with challengers
- requires a meaningful edge before switching
- prevents unnecessary over-switching
- uses protective rules such as minimum holding periods, probation, and cooldown logic

This matters because many strategies look great in research but fail in practice due to excessive switching, weak entries, or unstable leadership.

### What the strategy can hold

At any time, the strategy can be in only one of these states:

- **Cash**, if conditions are not strong enough
- **BTC**, if Bitcoin is the strongest valid choice
- **one shortlisted altcoin**, if it clearly earns the right to replace the current holding

In practice, this makes it a **top-1 rotation system with a cash option**.

### Why it sometimes stays in cash

Cash does not mean the system is “doing nothing.”  
It means the market is still below the required quality threshold, or no asset is strong enough to justify real exposure.

That is why the system may prefer an asset while still not taking the trade.
An asset may look attractive, but the safety layer may still block execution.

### What makes this strategy different

This is not just a simple ranking model.  
The strategy has three layers:

- **Market regime filter** – decides whether risk should be on at all
- **Asset selection layer** – finds the strongest valid asset
- **Governance layer** – decides whether a switch is actually justified

That third layer is important because it is often the difference between a model that looks good in a backtest and one that behaves in a disciplined way in real operation.

### Practical behavior

In practice, the strategy behaves very simply:

- stay in cash when market conditions are not strong enough
- otherwise hold the single strongest valid asset
- do not switch unless the challenger is clearly better
- avoid noisy, low-quality flips

### Why we use the last closed day

Trades are executed after the day closes, with a one-day delay versus the strategy signal.  
Based on our tests, this approach is more stable and more profitable.
""",
        "contact_title": "Contact",
        "contact_desc": "If the strategy caught your interest, you want a partnership, or you want to ask something, leave your email and a short message here. I will reply only to relevant messages.",
        "contact_email": "Email",
        "contact_type": "Message type",
        "contact_message": "Message",
        "contact_placeholder": "Write briefly what you want, what interests you, or what you need help with...",
        "contact_send": "Save message",
        "contact_saved": "Message saved.",
        "contact_need_input": "Fill in both email and message.",
        "contact_bad_email": "Enter a valid email.",
        "contact_failed": "Saving message failed",
        "contact_files": "Saved to: contact/contact_log.csv",
        "contact_type_options": ["Question", "Product interest", "Partnership", "Bug / issue", "Other"],
        "missing_files": "Missing required files:",
        "load_failed": "Failed to load data",
        "account_title": "Account",
        "account_snapshot_note": "Read-only exchange/account snapshot. This is an operational view, not the official strategy state.",
        "account_connection": "Connection status",
        "account_last_sync": "Last sync",
        "account_total_value": "Total account value",
        "account_available_balance": "Available balance",
        "account_open_position": "Open position",
        "account_open_orders": "Open orders",
        "account_recent_fills": "Recent fills",
        "account_provider": "Provider",
        "account_address": "Account address",
        "account_copy_address": "Copy full address",
        "account_last_action": "Latest check",
        "account_last_result": "Outcome",
        "account_position_details": "Position details",
        "account_no_position": "No open position",
        "account_position_empty_note": "There is currently no open position on the account.",
        "account_symbol": "Symbol",
        "account_side": "Side",
        "account_size": "Size",
        "account_entry_price": "Entry price",
        "account_mark_price": "Mark price",
        "account_unrealized_pnl_usd": "Unrealized PnL USD",
        "account_unrealized_pnl_pct": "Unrealized PnL %",
        "account_long": "Long",
        "account_short": "Short",
        "account_status_ok": "OK",
        "account_status_unavailable": "Unavailable",
        "btc_label": "BTC Buy & Hold",
        "cash": "CASH",
    },
}

METRIC_HELP = {
    "sk": {
        "Modelová pozícia": "Toto pole ide priamo z product snapshotu cez held_asset_public. App si ho sama nedopočítava.",
        "Stav trendu": "Textový stav exportovaný zo stratégie, nie vypočítaný v appke.",
        "Trend score": "Source-of-truth trend hodnota od -1 po +1. Pod nulou je trend pod buy hranou, nad nulou nad ňou.",
        "Buy threshold": "Hranica 0.0, ktorú používa core vrstva.",
        "Live režim": "Aktuálny live režim, ktorý app číta priamo z live status exportu.",
        "Aktuálny profil": "Profil, podľa ktorého je systém momentálne nastavený.",
        "Fallback profil": "Záložný profil pripravený pre prípad, že hlavný leverage deployment profil nebude vhodný.",
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
        "Model position": "This field is read directly from held_asset_public in the product snapshot.",
        "Trend state": "Text state exported by the strategy layer.",
        "Trend score": "Source-of-truth trend value from -1 to +1.",
        "Buy threshold": "The 0.0 threshold used by the core layer.",
        "Live mode": "The current live mode read directly from the live status export.",
        "Current profile": "The profile the system is currently configured to use.",
        "Fallback profile": "The backup profile prepared in case the main leverage deployment profile is not suitable.",
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

TEXT["sk"]["performance_fee_note"] = (
    "Top karty zobrazuju aktualne validovane metriky strategie. "
    "Vysledky uz zahrnaju Hyperliquid poplatky."
)
TEXT["en"]["performance_fee_note"] = (
    "Top cards show the current validated strategy metrics. "
    "Results already include Hyperliquid fees."
)
TEXT["sk"].update(
    {
        "currently_holding": "Aktualny stav",
        "production_candidate_asset": "Model preferuje",
        "production_market_state": "Realny ucet",
        "production_market_exposure": "Realny ucet / expozicia",
        "production_state_out_of_market": "Mimo trhu",
        "production_state_in_market": "V trhu",
        "production_wait_reason_pending": "Trend zatial nepotvrdil vstup",
        "production_wait_reason_active": "Vstup je potvrdeny",
        "production_candidate_hint": "Signal strategie, nie stav uctu",
        "production_exposure_hint_out": "Ucet je mimo trhu",
        "production_exposure_hint_in": "Ucet ma otvorenu trhovu expoziciu",
        "buy_threshold": "Hranica vstupu",
        "trend_desc": "Toto je oficialny pohlad na stav trendu. Aplikacia ho nepocita nanovo, len zobrazuje validovanu hodnotu.",
        "trend_threshold_note": "Biela hranica ukazuje bod, od ktoreho sa trend povazuje za dostatocne silny. Pod nou je strategia opatrnejsia.",
        "chart_title": "Modelový vývoj vs BTC",
        "chart_performance_axis": "Modelovy index",
        "trade_count": "Pocet obchodov",
        "current_drawdown": "Aktualny drawdown",
        "production_chart_note": "Graf ukazuje modelovy vyvoj vs BTC. Nejde o vypis realneho uctu ani potvrdenie otvorenej pozicie.",
        "production_chart_flat_note": "Rovne useky v tomto grafe neznamenaju novy nakup. Znamenaju len to, ze modelova hodnota sa v danom useku menila malo alebo vobec.",
        "production_chart_legend": "Model",
        "production_chart_subtitle": "Modelova kapitalova seria",
        "production_hover_date": "Datum",
        "production_hover_index": "Modelovy index",
        "production_hover_return_net": "Denny pohyb modelu",
        "production_reason_title": "Preto je strategia teraz v tomto stave",
        "production_wait_title": "Na co teraz caka",
        "production_pain_title": "Co ju teraz brzdi",
        "production_signal_health": "Stav dat",
        "production_validation_passed": "validovane",
        "production_validation_failed": "nevalidne",
        "production_status_now": "Co robi teraz",
        "production_status_why": "Preco to robi",
        "production_status_change": "Co by zmenilo spravanie",
        "production_status_risks": "Aktualne slabe miesta",
        "production_waiting_yes": "Ano",
        "production_waiting_no": "Nie",
        "production_waiting_label": "Caka na zmenu",
        "production_data_source_note": "Stranka zobrazuje iba oficialne validovany stav strategie.",
        "production_wait_current": "Dnesne hodnoty",
        "production_wait_target": "Hodnota pre zmenu",
    }
)
TEXT["en"].update(
    {
        "production_candidate_asset": "Model prefers",
        "production_market_state": "Real account",
        "production_market_exposure": "Real account / exposure",
        "production_state_out_of_market": "Out of market",
        "production_state_in_market": "In market",
        "production_wait_reason_pending": "Trend has not confirmed entry yet",
        "production_wait_reason_active": "Entry is confirmed",
        "production_candidate_hint": "Strategy signal, not account state",
        "production_exposure_hint_out": "Account is out of market",
        "production_exposure_hint_in": "Account has open market exposure",
        "buy_threshold": "Entry threshold",
        "trade_count": "Trade count",
        "current_drawdown": "Current drawdown",
        "production_chart_note": "This chart shows only the strategy equity curve. It is not a record of a physically bought coin or a list of open positions.",
        "production_chart_flat_note": "Flat segments do not mean a new buy. They only mean the capital changed little or not at all in that span.",
        "production_chart_legend": "Strategy capital",
        "production_chart_subtitle": "Official strategy capital series",
        "production_hover_date": "Date",
        "production_hover_index": "Capital index",
        "production_hover_return_net": "Daily net return",
        "production_status_now": "What it is doing now",
        "production_status_why": "Why it is doing that",
        "production_status_change": "What would change the behavior",
        "production_status_risks": "Current weak spots",
        "production_waiting_label": "Waiting for change",
        "production_data_source_note": "The page shows only the officially validated strategy state.",
    }
)
TEXT["sk"]["chart_note_strip_hidden"] = (
    "Horna krivka ukazuje vykon hlavneho modelu proti BTC benchmarku. "
    "Spodny pas je skryty, pretoze drzany stav momentalne nie je mozne "
    "zobrazit dostatocne spolahlivo."
)
TEXT["en"]["chart_note_strip_hidden"] = (
    "The top line shows the main model versus the BTC benchmark. "
    "The lower strip is hidden because the held state cannot currently "
    "be displayed reliably enough."
)
TEXT["sk"].update(
    {
        "production_core_error_prefix": "Stranka je docasne nedostupna",
        "production_exposure": "Modelový signál",
        "production_closed_day": "Posledny uzavrety den",
        "production_next_rebalance": "Najblizsi rebalance",
        "production_chart_note": "Graf ukazuje modelový vývoj vs BTC. Nie je to výpis reálneho účtu ani potvrdenie otvorenej pozície.",
        "production_chart_baseline_note": "Krivka Model je modelovy vyvoj. Zlata krivka je BTC baseline prepocitana zo zaverecnych cien a rebased na rovnaky zaciatok zobrazeneho obdobia.",
        "production_chart_flat_note": "Ked modelovy signal nema povolenu modelovu expoziciu, modelova kapitalova seria zostava rovna okrem explicitnych nakladov na prechod.",
        "production_chart_participation_note": "Spodny strip ukazuje historicky modelovy signal, nie vypis realnej penazenky ani potvrdenie otvorenej pozicie.",
        "production_reason_title": "Preto je strategia teraz v tomto stave",
        "production_wait_title": "Na co strategia caka",
        "production_pain_title": "Co ju teraz brzdi",
        "production_recent_rebalances": "Nedavne rebalance udalosti",
        "production_recent_regimes": "Nedavne zmeny rezimu",
        "production_wait_current": "Dnesne hodnoty",
        "production_wait_target": "Cielova podmienka",
        "production_signal_health": "Stav dat",
        "production_validation_passed": "validovane",
        "production_validation_failed": "nevalidne",
        "production_waiting_yes": "Ano",
        "production_waiting_no": "Nie",
        "production_chart_exposure_legend": "Modelový signál",
        "production_chart_btc_legend": "BTC baseline",
        "production_chart_exposure_axis": "Modelový signál",
        "production_hover_market_state": "Modelovy stav",
        "production_hover_authorized_exposure": "Modelový signál",
        "production_hover_candidate_asset": "Preferovane aktivum",
        "production_hover_btc_close": "BTC close",
        "production_hover_btc_return": "Denny pohyb BTC",
        "production_hover_btc_index": "BTC index",
        "production_hover_market_state_in": "SIGNAL AKTIVNY",
        "production_hover_market_state_out": "SIGNAL CASH",
        "production_chart_current_prefix": "Aktualne",
        "production_chart_current_out_note": "Aktualne je modelovy signal mimo trhu. Graf nie je vypis otvorenej pozicie. Model preferuje {candidate} a modelovy signal je {exposure}.",
        "production_chart_current_in_note": "Aktualne je modelovy signal aktivny s velkostou {exposure}. Model preferuje {candidate}.",
    }
)
TEXT["en"].update(
    {
        "production_core_error_prefix": "Page temporarily unavailable",
        "production_exposure": "Exposure",
        "production_closed_day": "Last closed day",
        "production_next_rebalance": "Next rebalance",
        "production_chart_note": "This chart shows only the model capital series and the BTC baseline. The real account state is separated in the top card.",
        "production_chart_baseline_note": "The red line is the authorized strategy. The gold line is a BTC baseline built from closing prices and rebased to the same start of the visible period.",
        "production_chart_flat_note": "When the strategy has no authorized market exposure, authorized capital should stay flat except for explicit transition costs.",
        "production_chart_participation_note": "The lower strip shows the historical model signal, not a wallet statement or proof of an open position.",
        "production_reason_title": "Why the strategy is in this state",
        "production_wait_title": "What the strategy is waiting for",
        "production_pain_title": "Current pain points",
        "production_recent_rebalances": "Recent rebalance events",
        "production_recent_regimes": "Recent regime changes",
        "production_wait_current": "Current values",
        "production_wait_target": "Target condition",
        "production_signal_health": "Signal health",
        "production_validation_passed": "validated",
        "production_validation_failed": "invalid",
        "production_waiting_yes": "Yes",
        "production_waiting_no": "No",
        "production_chart_exposure_legend": "Model signal",
        "production_chart_btc_legend": "BTC baseline",
        "production_chart_exposure_axis": "Model signal",
        "production_hover_market_state": "Model state",
        "production_hover_authorized_exposure": "Model signal",
        "production_hover_candidate_asset": "Preferred asset",
        "production_hover_btc_close": "BTC close",
        "production_hover_btc_return": "BTC daily move",
        "production_hover_btc_index": "BTC index",
        "production_hover_market_state_in": "SIGNAL IN MARKET",
        "production_hover_market_state_out": "SIGNAL OUT OF MARKET",
        "production_chart_current_prefix": "Current",
        "production_chart_current_out_note": "The current model signal is out of market. The chart is not an open-position statement. The model prefers {candidate} and the model signal is {exposure}.",
        "production_chart_current_in_note": "The current model signal is in market with size {exposure}. The model prefers {candidate}.",
    }
)
METRIC_HELP["sk"].update(
    {
        TEXT["sk"]["cagr"]: (
            "Tato top karta ukazuje aktualny CAGR z validovanych dat strategie."
        ),
        TEXT["sk"]["since2023"]: (
            "Tato top karta ukazuje okno CAGR od 2023 z validovanych dat strategie."
        ),
        TEXT["sk"]["since_etf_start"]: (
            "Tato top karta ukazuje verejne ETF okno CAGR od 12.1.2024."
        ),
        TEXT["sk"]["since2025"]: (
            "Tato top karta ukazuje okno CAGR od 2025 z validovanych dat strategie."
        ),
        TEXT["sk"]["currently_holding"]: "Toto pole ukazuje oficialny aktualny stav strategie.",
        TEXT["sk"]["trend_state"]: "Textovy stav trendu vychadza z poslednych validovanych dat.",
        TEXT["sk"]["trend_score"]: "Trend score a jeho historia vychadzaju z validovanej casovej serie.",
        TEXT["sk"]["buy_threshold"]: "Hranica vstupu sa cita z posledneho validovaneho dna.",
        TEXT["sk"]["total_return"]: "Celkovy vynos vychadza z validovanych metrik strategie.",
        TEXT["sk"]["sharpe"]: "Sharpe ratio sa pocita z autorizovanych dennych netto vynosov.",
        TEXT["sk"]["sortino"]: "Sortino ratio sa pocita z autorizovanych dennych netto vynosov.",
        TEXT["sk"]["max_dd"]: "Max drawdown vychadza z validovanych metrik strategie.",
        TEXT["sk"]["switch_count"]: "Pocet prepnuti vychadza z validovanej historie strategie.",
        TEXT["sk"]["trade_count"]: "Pocet obchodov vychadza z validovanej historie strategie.",
        TEXT["sk"]["current_drawdown"]: "Aktualny drawdown vychadza z posledneho rozhodovacieho stavu.",
        TEXT["sk"]["cash_days"]: "Cash Days vychadzaju z validovanych metrik strategie.",
        TEXT["sk"]["btc_days"]: "BTC Days vychadzaju z validovanych metrik strategie.",
        TEXT["sk"]["production_exposure"]: "Expozicia ukazuje modelovy signal strategie, nie realnu expoziciu uctu.",
        TEXT["sk"]["production_candidate_asset"]: "Model preferuje aktualny vyber strategie. Nie je to potvrdenie otvorenej pozicie na ucte.",
        TEXT["sk"]["production_market_state"]: "Realny ucet ukazuje stav po vykonani a po bezpecnostnych kontrolach.",
        TEXT["sk"]["production_market_exposure"]: "Realny ucet / expozicia ukazuje, ci ma ucet otvorenu trhovu expoziciu.",
        TEXT["sk"]["production_closed_day"]: "Posledny uzavrety den ukazuje datum poslednych validovanych dat.",
    }
)
METRIC_HELP["en"].update(
    {
        TEXT["en"]["cagr"]: (
            "This top card shows the current CAGR from validated strategy data."
        ),
        TEXT["en"]["since2023"]: (
            "This top card shows the since-2023 CAGR from validated strategy data."
        ),
        TEXT["en"]["since_etf_start"]: (
            "This top card shows the public ETF CAGR window from 2024-01-12."
        ),
        TEXT["en"]["since2025"]: (
            "This top card shows the since-2025 CAGR from validated strategy data."
        ),
        TEXT["en"]["currently_holding"]: "This field shows the official current strategy state.",
        TEXT["en"]["trend_state"]: "The trend state comes from the latest validated data.",
        TEXT["en"]["trend_score"]: "The trend score and its history come from the validated time series.",
        TEXT["en"]["buy_threshold"]: "The entry threshold is read from the latest validated day.",
        TEXT["en"]["total_return"]: "Total return comes from validated strategy metrics.",
        TEXT["en"]["sharpe"]: "Sharpe ratio is computed from authorized daily net returns.",
        TEXT["en"]["sortino"]: "Sortino ratio is computed from authorized daily net returns.",
        TEXT["en"]["max_dd"]: "Max drawdown comes from validated strategy metrics.",
        TEXT["en"]["switch_count"]: "Switch count comes from validated strategy history.",
        TEXT["en"]["trade_count"]: "Trade count comes from validated strategy history.",
        TEXT["en"]["current_drawdown"]: "Current drawdown comes from the latest decision state.",
        TEXT["en"]["cash_days"]: "Cash Days come from validated strategy metrics.",
        TEXT["en"]["btc_days"]: "BTC Days come from validated strategy metrics.",
        TEXT["en"]["production_exposure"]: "Exposure shows the strategy model signal, not the real account exposure.",
        TEXT["en"]["production_candidate_asset"]: "The model preference is the current strategy choice. It is not confirmation of an open account position.",
        TEXT["en"]["production_market_state"]: "Real account shows the state after execution and safety checks.",
        TEXT["en"]["production_market_exposure"]: "Real account / exposure shows whether the account has open market exposure.",
        TEXT["en"]["production_closed_day"]: "The last closed day shows the date of the latest validated data.",
    }
)

ACCOUNT_UI_COPY = {
    "sk": {
        "observability_disabled": "Prevadzkovy prehlad uctu je v oficialnom kontrakte momentalne vypnuty.",
        "proof_banner": "Prevadzkovy prehlad uctu",
        "proof_state": "Stav potvrdenia exekucie",
        "read_mode": "Rezim citania",
        "mode": "Prevadzkovy rezim",
        "overview": "Prehlad",
        "balances": "Zostatky",
        "positions": "Pozicie",
        "activity": "Aktivita",
        "runtime_error": "Posledna znama chyba",
    },
    "en": {
        "observability_disabled": "Account observability is currently disabled in the official contract.",
        "proof_banner": "Execution observability",
        "proof_state": "Execution proof state",
        "read_mode": "Read mode",
        "mode": "Operating mode",
        "overview": "Overview",
        "balances": "Balances",
        "positions": "Positions",
        "activity": "Activity",
        "runtime_error": "Latest known error",
    },
}

TEXT["sk"].update(
    {
        "account_snapshot_note": "Jednoduchy prehlad aktualneho stavu uctu.",
        "account_provider": "Burza",
        "account_last_action": "Posledna akcia",
        "account_last_result": "Vysledok",
        "account_position_details": "Pozicia",
        "account_no_position": "Ziadna otvorena pozicia",
        "account_position_empty_note": "Na ucte momentalne nie je otvorena ziadna pozicia.",
        "account_entry_price": "Vstupna cena",
        "account_mark_price": "Aktualna cena",
        "account_unrealized_pnl_usd": "Zisk / strata",
        "account_unrealized_pnl_pct": "Zisk / strata %",
        "account_long": "Nakupna",
        "account_short": "Predajna",
        "account_status_ok": "V poriadku",
    }
)

ACCOUNT_UI_COPY["sk"].update(
    {
        "proof_banner": "",
        "proof_state": "Poznamka",
        "read_mode": "",
        "mode": "",
        "balances": "Zostatok",
        "positions": "Pozicia",
        "activity": "Posledna zmena",
        "runtime_error": "Upozornenie",
    }
)

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


def account_ui_text(lang: str, key: str) -> str:
    return ACCOUNT_UI_COPY.get(lang, ACCOUNT_UI_COPY["en"]).get(key, key)


def localized_contract_text(value, lang: str) -> str:
    if isinstance(value, dict):
        text = value.get(lang) or value.get("en") or value.get("sk")
        return str(text).strip() if text else ""
    if value is None:
        return ""
    return str(value).strip()


def safe_metric_text(value, decimals: int = 2, suffix: str = "%", lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return f"{number:.{decimals}f}{suffix}"


def safe_day_metric_text(value, lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return "N/A"
    return safe_metric_text(number, lang=lang)


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


def safe_usd_text(value, decimals: int = 2, lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return f"${number:,.{decimals}f}"


def safe_signed_usd_text(value, decimals: int = 2, lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return f"{number:+,.{decimals}f} USD"


def resolve_main_metrics_for_display(
    source_metrics: dict[str, Any],
    main_strategy_model: str | None,
) -> dict[str, Any]:
    metrics = dict(source_metrics or {})

    fallback_fields = {
        "total_return_pct": ["total_return_pct_net", "total_return_pct_gross"],
        "cagr_pct": ["cagr_pct_net", "cagr_pct_gross"],
        "max_drawdown_pct": ["max_drawdown_pct_net", "max_drawdown_pct_gross"],
        "since2023_cagr_pct": ["since2023_cagr_pct_net", "since2023_cagr_pct_gross"],
        "since2025_cagr_pct": ["since2025_cagr_pct_net", "since2025_cagr_pct_gross"],
    }
    for field, candidates in fallback_fields.items():
        if field in metrics:
            continue
        for candidate in candidates:
            if candidate in metrics:
                metrics[field] = metrics[candidate]
                break

    expected_model = str(main_strategy_model or "").strip()
    actual_model = str(metrics.get("model") or "").strip()
    if expected_model and actual_model and actual_model != expected_model:
        raise ValueError(
            "Homepage load blocked: current main strategy metric source model diverged "
            f"(expected={expected_model} actual={actual_model})"
        )
    if expected_model and not actual_model:
        metrics["model"] = expected_model
    return metrics


def _to_bool_series(values: pd.Series) -> pd.Series:
    lowered = values.fillna("").astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y"})


def _compute_total_return_pct(series: pd.Series) -> float:
    curve = (1.0 + pd.to_numeric(series, errors="coerce").fillna(0.0)).cumprod()
    if curve.empty:
        return 0.0
    return float((curve.iloc[-1] - 1.0) * 100.0)


def _compute_cagr_pct(series: pd.Series, dates: pd.Series) -> float:
    clean_returns = pd.to_numeric(series, errors="coerce").fillna(0.0)
    clean_dates = pd.to_datetime(dates, errors="coerce")
    valid_mask = clean_dates.notna()
    clean_returns = clean_returns.loc[valid_mask]
    clean_dates = clean_dates.loc[valid_mask]
    if len(clean_returns) < 2:
        return 0.0
    start_dt = pd.Timestamp(clean_dates.iloc[0])
    end_dt = pd.Timestamp(clean_dates.iloc[-1])
    day_count = max(int((end_dt - start_dt).days), 1)
    years = day_count / 365.25
    if years <= 0:
        return 0.0
    ending_equity = float((1.0 + clean_returns).cumprod().iloc[-1])
    if ending_equity <= 0:
        return 0.0
    return float(((ending_equity ** (1.0 / years)) - 1.0) * 100.0)


def _compute_cagr_since(series: pd.Series, dates: pd.Series, start_day: str) -> float:
    clean_dates = pd.to_datetime(dates, errors="coerce")
    mask = clean_dates >= pd.Timestamp(start_day)
    if not mask.any():
        return _compute_cagr_pct(series, dates)
    return _compute_cagr_pct(series.loc[mask], clean_dates.loc[mask])


def _compute_average_annual_period_return_pct(series: pd.Series, dates: pd.Series) -> float:
    clean_returns = pd.to_numeric(series, errors="coerce").fillna(0.0)
    clean_dates = pd.to_datetime(dates, errors="coerce")
    frame = pd.DataFrame({"return": clean_returns, "date": clean_dates}).dropna(subset=["date"])
    if frame.empty:
        return 0.0

    annual_returns_pct = []
    for _, year_frame in frame.groupby(frame["date"].dt.year, sort=True):
        year_equity = float((1.0 + pd.to_numeric(year_frame["return"], errors="coerce").fillna(0.0)).prod())
        annual_returns_pct.append((year_equity - 1.0) * 100.0)
    if not annual_returns_pct:
        return 0.0
    first_day = pd.Timestamp(frame["date"].min()).date()
    last_day = pd.Timestamp(frame["date"].max()).date()
    period_count = (last_day.year - first_day.year) + 1
    if first_day > date(first_day.year, 1, 1):
        period_count += 1
    return float(sum(annual_returns_pct) / max(period_count, 1))


def _compute_max_drawdown_pct(series: pd.Series) -> float:
    curve = (1.0 + pd.to_numeric(series, errors="coerce").fillna(0.0)).cumprod()
    if curve.empty:
        return 0.0
    drawdown = (curve / curve.cummax()) - 1.0
    return float(drawdown.min() * 100.0)


def _annualized_sharpe_from_daily_returns(series: pd.Series) -> float | None:
    daily_returns = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    variance = sum((value - mean_ret) ** 2 for value in daily_returns) / (len(daily_returns) - 1)
    if variance <= 0:
        return None
    std = variance ** 0.5
    if std == 0:
        return None
    return (mean_ret / std) * (365.0 ** 0.5)


def _annualized_sortino_from_daily_returns(series: pd.Series) -> float | None:
    daily_returns = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    downside = [value for value in daily_returns if value < 0]
    if len(downside) < 2:
        return None
    downside_mean = sum(downside) / len(downside)
    downside_variance = sum((value - downside_mean) ** 2 for value in downside) / (len(downside) - 1)
    if downside_variance <= 0:
        return None
    downside_std = downside_variance ** 0.5
    if downside_std == 0:
        return None
    return (mean_ret / downside_std) * (365.0 ** 0.5)


def normalize_iso_day_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def resolve_etf_public_evidence_start_day(production_snapshot: dict[str, Any]) -> str | None:
    strategy_version = str(production_snapshot.get("strategy_version") or "").strip()
    if strategy_version != ETF_FLOW_PUBLIC_STRATEGY_VERSION:
        return None
    source_inputs = (
        production_snapshot.get("source_inputs")
        if isinstance(production_snapshot.get("source_inputs"), dict)
        else {}
    )
    evidence_window = (
        source_inputs.get("etf_flow_evidence_window")
        if isinstance(source_inputs.get("etf_flow_evidence_window"), dict)
        else {}
    )
    return (
        normalize_iso_day_optional(evidence_window.get("start_date"))
        or ETF_FLOW_PUBLIC_EVIDENCE_START_DATE
    )


def build_public_homepage_performance_context(
    production_snapshot: dict[str, Any],
    production_timeseries_df: pd.DataFrame,
) -> dict[str, Any]:
    main_strategy_model = str(production_snapshot.get("strategy_version") or "").strip()
    base_metrics = resolve_main_metrics_for_display(
        dict(production_snapshot.get("metrics") or {}),
        main_strategy_model,
    )
    evidence_start_day = resolve_etf_public_evidence_start_day(production_snapshot)
    if not evidence_start_day:
        return {
            "timeseries_df": production_timeseries_df,
            "main_metrics": base_metrics,
            "top_performance_metrics": dict(base_metrics),
            "start_day": None,
        }

    filtered_df = production_timeseries_df[
        production_timeseries_df["ts"] >= pd.Timestamp(evidence_start_day)
    ].copy()
    if filtered_df.empty:
        return {
            "timeseries_df": production_timeseries_df,
            "main_metrics": base_metrics,
            "top_performance_metrics": dict(base_metrics),
            "start_day": evidence_start_day,
        }

    returns = pd.to_numeric(filtered_df["authorized_return_net"], errors="coerce").fillna(0.0)
    dates = pd.to_datetime(filtered_df["ts"], errors="coerce")
    transition_series = (
        filtered_df["asset_transition_day"]
        if "asset_transition_day" in filtered_df.columns
        else pd.Series(False, index=filtered_df.index)
    )
    public_metrics = dict(base_metrics)
    public_metrics.update(
        {
            "total_return_pct": round(_compute_total_return_pct(returns), 4),
            "cagr_pct": round(_compute_average_annual_period_return_pct(returns, dates), 4),
            "max_drawdown_pct": round(_compute_max_drawdown_pct(returns), 4),
            "public_window_cagr_pct": round(_compute_cagr_since(returns, dates, evidence_start_day), 4),
            "since2023_cagr_pct": round(_compute_cagr_since(returns, dates, evidence_start_day), 4),
            "since2025_cagr_pct": round(_compute_cagr_since(returns, dates, "2025-01-01"), 4),
            "cash_days_pct": round(float(_to_bool_series(filtered_df["cash_day"]).mean() * 100.0), 6),
            "btc_days_pct": round(float(_to_bool_series(filtered_df["btc_day"]).mean() * 100.0), 6),
            "switch_count": int(_to_bool_series(transition_series).sum()),
            "trade_count": int(_to_bool_series(transition_series).sum()),
            "public_performance_start_date": evidence_start_day,
        }
    )
    sharpe = _annualized_sharpe_from_daily_returns(returns)
    if sharpe is not None:
        public_metrics["sharpe"] = round(float(sharpe), 4)
    sortino = _annualized_sortino_from_daily_returns(returns)
    if sortino is not None:
        public_metrics["sortino"] = round(float(sortino), 4)
    return {
        "timeseries_df": filtered_df,
        "main_metrics": public_metrics,
        "top_performance_metrics": dict(public_metrics),
        "start_day": evidence_start_day,
        "public_window_label_key": "since_etf_start",
        "public_window_metric_key": "public_window_cagr_pct",
    }


def safe_plain_number_text(value, decimals: int = 4, lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return f"{number:,.{decimals}f}"


def safe_signed_pct_text(value, decimals: int = 2, lang: str = "sk") -> str:
    number = as_float(value)
    if number is None:
        return t(lang, "na")
    return f"{number:+.{decimals}f}%"


def load_json_optional(path_value: str | Path | None) -> dict:
    path = normalize_path(path_value)
    if path is None or not path.exists():
        return {}
    try:
        # Authority JSON must stay uncached in Streamlit so each rerun reads the
        # latest on-disk payload directly.
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_live_data_health_report() -> dict[str, Any]:
    report = load_json_optional(DATA_HEALTH_REPORT_PATH)
    if report.get("artifact_type") == REPORT_ARTIFACT_TYPE:
        return report
    bundle = build_report_bundle(
        root=ROOT,
        output_dir=PRODUCTION_OUTPUTS,
        write_outputs=False,
    )
    return dict(bundle["report"])


def parse_iso_datetime_optional(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def unique_source_id_list(values: Any) -> list[str]:
    source_ids: list[str] = []
    seen_source_ids: set[str] = set()
    for value in values if isinstance(values, list) else []:
        source_id = str(value or "").strip()
        if not source_id or source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        source_ids.append(source_id)
    return source_ids


def report_sources_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = report.get("sources") if isinstance(report.get("sources"), list) else []
    indexed_sources: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "").strip()
        if not source_id or source_id in indexed_sources:
            continue
        indexed_sources[source_id] = source
    return indexed_sources


def authority_payload_target_day(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    product_snapshot = (
        payload.get("app_product_snapshot")
        if isinstance(payload.get("app_product_snapshot"), dict)
        else {}
    )
    return str(
        payload.get("target_closed_day_utc")
        or payload.get("strategy_artifact_closed_day_utc")
        or product_snapshot.get("strategy_last_closed_day")
        or ""
    ).strip()


def authority_payload_sort_key(payload: dict[str, Any]) -> tuple[str, datetime]:
    if not isinstance(payload, dict):
        return "", datetime(1970, 1, 1, tzinfo=timezone.utc)
    payload_timestamp = (
        parse_iso_datetime_optional(payload.get("generated_at_utc"))
        or parse_iso_datetime_optional(payload.get("refresh_finished_at_utc"))
        or parse_iso_datetime_optional(payload.get("refresh_started_at_utc"))
        or datetime(1970, 1, 1, tzinfo=timezone.utc)
    )
    return authority_payload_target_day(payload), payload_timestamp


def select_preferred_authority_payload(
    latest_successful_snapshot: dict[str, Any],
    latest_attempt_status: dict[str, Any],
) -> tuple[dict[str, Any], Path, str]:
    attempt_payload = latest_attempt_status if isinstance(latest_attempt_status, dict) else {}
    success_payload = latest_successful_snapshot if isinstance(latest_successful_snapshot, dict) else {}
    if not attempt_payload:
        return success_payload, AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH, SUCCESS_SNAPSHOT_ARTIFACT_TYPE
    if not success_payload:
        return attempt_payload, AUTHORITY_LATEST_ATTEMPT_STATUS_PATH, ATTEMPT_STATUS_ARTIFACT_TYPE
    if authority_payload_sort_key(success_payload) > authority_payload_sort_key(attempt_payload):
        return success_payload, AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH, SUCCESS_SNAPSHOT_ARTIFACT_TYPE
    return attempt_payload, AUTHORITY_LATEST_ATTEMPT_STATUS_PATH, ATTEMPT_STATUS_ARTIFACT_TYPE


def build_homepage_data_health_status_model(
    report: dict[str, Any],
    latest_successful_snapshot: dict[str, Any],
    latest_attempt_status: dict[str, Any],
) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    sources_by_id = report_sources_by_id(report)
    app_blocking_source_ids = unique_source_id_list(summary.get("app_blocking_source_ids"))
    execution_blocking_source_ids = unique_source_id_list(summary.get("execution_blocking_source_ids"))
    critical_source_ids = unique_source_id_list(
        [*app_blocking_source_ids, *execution_blocking_source_ids]
    )
    critical_sources = [
        sources_by_id[source_id]
        for source_id in critical_source_ids
        if source_id in sources_by_id
    ]
    research_sources = research_warning_sources(report)
    informational_sources = informational_warning_sources(report)
    block_app = summary.get("block_app") is True or bool(app_blocking_source_ids)
    block_execution = summary.get("block_execution") is True or bool(execution_blocking_source_ids)
    preferred_authority_payload, preferred_authority_source_path, preferred_authority_source_type = (
        select_preferred_authority_payload(
            latest_successful_snapshot,
            latest_attempt_status,
        )
    )
    authority_attempt_status = str(
        preferred_authority_payload.get("latest_authoritative_attempt_status") or ""
    ).strip().lower()
    authority_currentness_state, authority_currentness_reason, currentness_source_path, currentness_source_type = (
        _derive_authority_currentness(
            latest_successful_snapshot,
            latest_attempt_status,
        )
    )
    authority_target_day = authority_payload_target_day(preferred_authority_payload)
    report_reference_day = str(report.get("reference_closed_day_utc") or "").strip()
    report_matches_authority_target = bool(
        report_reference_day and authority_target_day and report_reference_day == authority_target_day
    )
    report_stale_relative_to_authority = bool(
        report_reference_day and authority_target_day and report_reference_day != authority_target_day
    )

    public_notice_reason: str | None = None
    if authority_currentness_state == "refresh_failed":
        public_notice_reason = "authority_refresh_failed"
    elif block_app or block_execution:
        public_notice_reason = "data_health_blocked"
    elif report_stale_relative_to_authority:
        public_notice_reason = "data_health_report_stale"
    elif authority_currentness_state in {"stale", "missing_authority_artifact"}:
        public_notice_reason = f"authority_{authority_currentness_state}"

    status_model = {
        "block_app": block_app,
        "block_execution": block_execution,
        "critical_sources": critical_sources,
        "critical_source_ids": critical_source_ids,
        "research_sources": research_sources,
        "research_source_ids": [
            str(source.get("source_id") or "").strip()
            for source in research_sources
            if isinstance(source, dict)
        ],
        "informational_sources": informational_sources,
        "informational_source_ids": [
            str(source.get("source_id") or "").strip()
            for source in informational_sources
            if isinstance(source, dict)
        ],
        "authority_attempt_status": authority_attempt_status,
        "authority_currentness_state": authority_currentness_state,
        "authority_currentness_reason": authority_currentness_reason,
        "authority_target_day": authority_target_day,
        "preferred_authority_source_path": preferred_authority_source_path,
        "preferred_authority_source_type": preferred_authority_source_type,
        "currentness_source_path": currentness_source_path,
        "currentness_source_type": currentness_source_type,
        "report_reference_day": report_reference_day,
        "report_matches_authority_target": report_matches_authority_target,
        "report_stale_relative_to_authority": report_stale_relative_to_authority,
        "show_public_notice": public_notice_reason is not None,
        "public_notice_reason": public_notice_reason,
        "show_ok_status": public_notice_reason is None,
        "show_secondary_note": public_notice_reason is None
        and bool(research_sources or informational_sources),
    }
    assert_homepage_data_health_status_model(status_model)
    return status_model


def assert_homepage_data_health_status_model(status_model: dict[str, Any]) -> None:
    if (
        status_model.get("authority_attempt_status") == "success"
        and status_model.get("authority_currentness_state") == "current"
        and status_model.get("report_matches_authority_target") is True
        and status_model.get("block_app") is False
        and status_model.get("block_execution") is False
    ):
        assert not status_model.get("critical_source_ids"), (
            "Healthy current authority/report state must not render critical production/app/execution rows."
        )
        assert status_model.get("show_public_notice") is False, (
            "Healthy current authority/report state must not render the daily update problem banner."
        )


def data_health_messages_for_lang(sources: list[dict[str, Any]], lang: str) -> list[str]:
    message_key = "user_message_sk" if lang == "sk" else "user_message_en"
    messages: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        message = str(source.get(message_key) or "").strip()
        if message:
            messages.append(message)
    return messages


def data_health_rows_for_lang(sources: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    source_label_column = "Zdroj" if lang == "sk" else "Source"
    status_label_column = "Stav" if lang == "sk" else "Status"
    detail_label_column = "Detail" if lang == "sk" else "Detail"
    label_key = "label_sk" if lang == "sk" else "label_en"
    message_key = "user_message_sk" if lang == "sk" else "user_message_en"
    rows: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        rows.append(
            {
                source_label_column: safe_text_value(source.get(label_key), lang=lang),
                status_label_column: safe_text_value(source.get("status"), lang=lang),
                detail_label_column: safe_text_value(source.get(message_key), lang=lang),
            }
        )
    return rows


def authority_success_closed_day_text(latest_successful_snapshot: dict) -> str:
    success_payload = latest_successful_snapshot if isinstance(latest_successful_snapshot, dict) else {}
    product_snapshot = (
        success_payload.get("app_product_snapshot")
        if isinstance(success_payload.get("app_product_snapshot"), dict)
        else {}
    )
    return str(
        success_payload.get("strategy_artifact_closed_day_utc")
        or success_payload.get("target_closed_day_utc")
        or product_snapshot.get("strategy_last_closed_day")
        or ""
    ).strip()


def build_public_homepage_refresh_notice(
    status_model: dict[str, Any],
    latest_successful_snapshot: dict,
    lang: str,
) -> str | None:
    success_closed_day = authority_success_closed_day_text(latest_successful_snapshot)
    success_suffix = (
        (
            f" Zobrazuju sa posledne uspesne data k {success_closed_day}. Detaily su v Stav dat."
            if success_closed_day
            else " Zobrazuju sa posledne uspesne data. Detaily su v Stav dat."
        )
        if lang == "sk"
        else (
            f" Showing the latest successful data for {success_closed_day}. Details are in Data Health."
            if success_closed_day
            else " Showing the latest successful data. Details are in Data Health."
        )
    )
    public_notice_reason = str(status_model.get("public_notice_reason") or "").strip().lower()
    report_reference_day = str(status_model.get("report_reference_day") or "").strip()
    authority_target_day = str(status_model.get("authority_target_day") or "").strip()
    stale_report_suffix = ""
    if status_model.get("report_stale_relative_to_authority"):
        stale_report_suffix = (
            (
                f" Aktualny report je pre {report_reference_day or 'n/a'}, "
                f"cielovy den je {authority_target_day or 'n/a'}."
            )
            if lang == "sk"
            else (
                f" The current report is for {report_reference_day or 'n/a'}, "
                f"while the target day is {authority_target_day or 'n/a'}."
            )
        )

    if public_notice_reason == "authority_refresh_failed":
        return (
            "Dnesny refresh zlyhal." + stale_report_suffix + success_suffix
            if lang == "sk"
            else "Today's refresh failed." + stale_report_suffix + success_suffix
        )
    if public_notice_reason == "data_health_blocked":
        return (
            "Dnesna aktualizacia ma kriticky problem." + stale_report_suffix + success_suffix
            if lang == "sk"
            else "Today's update has a critical issue." + stale_report_suffix + success_suffix
        )
    if public_notice_reason == "data_health_report_stale":
        return (
            "Report nie je zosynchronizovany s poslednym cielovym dnom."
            + stale_report_suffix
            + success_suffix
            if lang == "sk"
            else "The report is not aligned with the latest target day."
            + stale_report_suffix
            + success_suffix
        )
    if public_notice_reason == "authority_stale":
        return (
            "Dnesny refresh nie je aktualny." + success_suffix
            if lang == "sk"
            else "Today's refresh is stale." + success_suffix
        )
    if public_notice_reason == "authority_missing_authority_artifact":
        return (
            "Stav aktualizacie nie je dostupny." + success_suffix
            if lang == "sk"
            else "Update status is unavailable." + success_suffix
        )
    return None


def render_data_health_banner(
    report: dict[str, Any],
    status_model: dict[str, Any],
    lang: str,
    latest_successful_snapshot: dict,
) -> bool:
    public_notice = build_public_homepage_refresh_notice(
        status_model,
        latest_successful_snapshot,
        lang,
    )
    if public_notice:
        st.warning(public_notice)
        return False
    if status_model["research_sources"] or status_model["informational_sources"]:
        st.caption(
            "Produk\u010dn\u00e9 d\u00e1ta: OK. Ved\u013eaj\u0161ie technick\u00e9 upozornenia s\u00fa skryt\u00e9 v detaile Stav d\u00e1t."
            if lang == "sk"
            else "Production data: OK. Secondary technical notices are tucked into the Data Health details."
        )
        return False
    st.caption("Produk\u010dn\u00e9 d\u00e1ta: OK" if lang == "sk" else "Production data: OK")
    return False

def render_data_health_details(
    report: dict[str, Any],
    status_model: dict[str, Any],
    lang: str,
    refresh_rows: list[dict[str, Any]],
) -> None:
    critical_rows = data_health_rows_for_lang(status_model["critical_sources"], lang)
    research_messages = data_health_messages_for_lang(status_model["research_sources"], lang)
    informational_messages = data_health_messages_for_lang(status_model["informational_sources"], lang)

    with st.expander("Stav d\u00e1t" if lang == "sk" else "Data Health", expanded=False):
        st.markdown(
            "#### Stav aktualizacie"
            if lang == "sk"
            else "#### Update Health"
        )
        if critical_rows:
            st.caption(
                "Verejna stranka dalej bezi z posledneho uspesneho validovaneho stavu. Ovladajuce kontroly zostavaju uzamknute, kym sa problem neodstrani."
                if lang == "sk"
                else "The public page keeps rendering from the latest successfully validated state. Control actions remain locked until the issue is resolved."
            )
            if status_model["report_stale_relative_to_authority"]:
                st.caption(
                    (
                        "Aktualny report zaostava za cielovym dnom "
                        f"{status_model.get('authority_target_day') or 'n/a'}."
                    )
                    if lang == "sk"
                    else (
                        "The current report lags the target day "
                        f"{status_model.get('authority_target_day') or 'n/a'}."
                    )
                )
            render_app_table(critical_rows, emphasize_first_column=True)
        elif status_model["report_stale_relative_to_authority"]:
            st.warning(
                (
                    "Report momentalne nehlasi kriticky problem, "
                    "ale este nie je zosynchronizovany s poslednym cielovym dnom."
                )
                if lang == "sk"
                else (
                    "The report currently shows no critical issue, "
                    "but it is not yet aligned with the latest target day."
                )
            )
        elif status_model["show_public_notice"]:
            st.warning(
                (
                    "Stranka zatial drzi posledny uspesny validovany stav, "
                    "ale najnovsi stav este nie je potvrdeny ako aktualny."
                )
                if lang == "sk"
                else (
                    "The page is still holding the latest successfully validated state, "
                    "but the newest state is not confirmed as current yet."
                )
            )
        elif status_model["show_ok_status"]:
            st.write(
                "Produk\u010dn\u00e9 d\u00e1ta a aplik\u00e1cia s\u00fa v poriadku."
                if lang == "sk"
                else "Production data and the app are healthy."
            )
            if status_model["show_secondary_note"]:
                st.caption(
                    "Nizsie su len vedlajsie technicke upozornenia. Verejny stav nimi nie je ovplyvneny."
                    if lang == "sk"
                    else "Only secondary technical notices remain below. The public state is not affected."
                )

        st.markdown("#### Posledna aktualizacia" if lang == "sk" else "#### Latest Update")
        render_app_table(refresh_rows, emphasize_first_column=True)

        if research_messages:
            st.markdown(
                "#### Vedlajsie upozornenia"
                if lang == "sk"
                else "#### Secondary Notices"
            )
            st.caption(
                "Verejny stav nimi nie je ovplyvneny."
                if lang == "sk"
                else "The public state is not affected."
            )
            st.markdown(f"- {len(research_messages)} upozorneni je skrytych." if lang == "sk" else f"- {len(research_messages)} notices are hidden.")

        if informational_messages:
            st.markdown(
                "#### Informacne upozornenia"
                if lang == "sk"
                else "#### Informational Notices"
            )
            st.caption(
                "Ide o pomocne upozornenia. Verejny stav nimi nie je ovplyvneny."
                if lang == "sk"
                else "These are auxiliary notices. The public state is not affected."
            )
            st.markdown(f"- {len(informational_messages)} upozorneni je skrytych." if lang == "sk" else f"- {len(informational_messages)} notices are hidden.")


def stop_for_production_homepage_block(message: str) -> None:
    lang = st.session_state.get("lang", "sk")
    st.error(f"{t(lang, 'load_failed')}: {t(lang, 'production_core_error_prefix')}.")
    st.stop()


def load_required_production_payload(
    path: Path,
    expected_type: str,
    *,
    context: str,
) -> dict[str, Any]:
    payload = load_json_optional(path)
    if not payload:
        stop_for_production_homepage_block(f"{context}: missing {path}")
    if payload.get("artifact_type") != expected_type:
        stop_for_production_homepage_block(
            f"{context}: expected {expected_type} at {path}"
        )
    return payload


def load_production_timeseries_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        stop_for_production_homepage_block(f"timeseries missing {path}")
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        stop_for_production_homepage_block(f"timeseries unreadable {path}: {exc}")
        return pd.DataFrame()

    required_columns = {
        "date",
        "strategy_id",
        "strategy_version",
        "candidate_asset",
        "selected_asset",
        "actual_held_asset",
        "authorized_tradable_asset",
        "held_asset",
        "market_state",
        "effective_market_exposure",
        "model_candidate_exposure",
        "trend_permission_active",
        "exposure",
        "regime",
        "execution_state",
        "execution_target_asset",
        "execution_target_exposure",
        "trend_state",
        "trend_score",
        "buy_threshold",
        "model_candidate_return_gross",
        "model_candidate_return_net",
        "model_candidate_equity",
        "authorized_return_gross",
        "authorized_return_net",
        "authorized_equity",
        "btc_close",
        "btc_return",
        "btc_baseline_equity",
        "btc_baseline_index",
        "equity",
        "reason_code",
        "source_validated",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        stop_for_production_homepage_block(
            "timeseries missing columns: " + ", ".join(missing_columns)
        )

    frame["ts"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    for numeric_column in [
        "exposure",
        "effective_market_exposure",
        "model_candidate_exposure",
        "execution_target_exposure",
        "trend_score",
        "buy_threshold",
        "trend_activation_threshold",
        "model_candidate_return_gross",
        "model_candidate_return_net",
        "model_candidate_equity",
        "authorized_return_gross",
        "authorized_return_net",
        "authorized_equity",
        "btc_close",
        "btc_return",
        "btc_baseline_equity",
        "btc_baseline_index",
        "equity",
        "drawdown_pct",
        "rolling_return_7d",
        "rolling_return_30d",
        "rolling_return_90d",
        "rolling_vol_30d",
        "rolling_sharpe_90d",
    ]:
        if numeric_column in frame.columns:
            frame[numeric_column] = pd.to_numeric(frame[numeric_column], errors="coerce")

    frame = (
        frame.dropna(
            subset=[
                "ts",
                "authorized_equity",
                "btc_close",
                "btc_baseline_equity",
                "btc_baseline_index",
            ]
        )
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    if frame.empty:
        stop_for_production_homepage_block("timeseries has no usable rows")
    return frame


def load_dashboard_public_chart_timeseries_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        stop_for_production_homepage_block(f"dashboard public chart missing {path}")
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        stop_for_production_homepage_block(f"dashboard public chart unreadable {path}: {exc}")
        return pd.DataFrame()

    required_columns = {
        "date",
        "live_strategy_index",
        "live_strategy_exposure_x",
        "live_strategy_return_net",
        "live_strategy_vs_btc_return",
        "live_strategy_source",
        "strategy_execution_index",
        "model_index",
        "btc_index",
        "strategy_execution_exposure_x",
        "strategy_execution_return_net",
        "strategy_execution_vs_btc_return",
        "strategy_execution_source",
        "model_authorized_exposure_x",
        "model_authorized_return_net",
        "model_authorized_return_gross",
        "model_transition_cost",
        "model_asset_transition_day",
        "real_account_index",
        "real_account_exposure_x",
        "real_account_return_net",
        "real_account_vs_btc_return",
        "real_account_source",
        "chart_scope",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        stop_for_production_homepage_block(
            "dashboard public chart missing columns: " + ", ".join(missing_columns)
        )

    frame["ts"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    for numeric_column in [
        "live_strategy_index",
        "live_strategy_exposure_x",
        "live_strategy_return_net",
        "live_strategy_vs_btc_return",
        "strategy_execution_index",
        "model_index",
        "btc_index",
        "strategy_execution_exposure_x",
        "strategy_execution_return_net",
        "strategy_execution_vs_btc_return",
        "model_authorized_exposure_x",
        "model_authorized_return_net",
        "model_authorized_return_gross",
        "model_transition_cost",
        "real_account_index",
        "real_account_exposure_x",
        "real_account_return_net",
        "real_account_vs_btc_return",
    ]:
        frame[numeric_column] = pd.to_numeric(frame[numeric_column], errors="coerce")

    frame = (
        frame.dropna(
            subset=[
                "ts",
                "live_strategy_index",
                "strategy_execution_index",
                "model_index",
                "btc_index",
                "live_strategy_exposure_x",
                "live_strategy_return_net",
                "strategy_execution_exposure_x",
                "strategy_execution_return_net",
                "model_authorized_exposure_x",
                "model_authorized_return_net",
            ]
        )
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    if frame.empty:
        stop_for_production_homepage_block("dashboard public chart has no usable rows")
    return frame


def production_chart_authorized_equity_series(df: pd.DataFrame) -> pd.Series:
    if "model_index" in df.columns:
        return pd.to_numeric(df["model_index"], errors="coerce")
    return pd.to_numeric(df.get("authorized_equity", pd.Series(index=df.index, dtype="float64")), errors="coerce")


def production_chart_authorized_gross_return_series(df: pd.DataFrame) -> pd.Series:
    if "model_authorized_return_gross" in df.columns:
        return pd.to_numeric(
            df["model_authorized_return_gross"],
            errors="coerce",
        ).fillna(0.0)
    return pd.to_numeric(
        df.get("authorized_return_gross", pd.Series(index=df.index, dtype="float64")),
        errors="coerce",
    ).fillna(0.0)


def production_chart_authorized_return_series(df: pd.DataFrame) -> pd.Series:
    if "model_authorized_return_net" in df.columns:
        return pd.to_numeric(
            df["model_authorized_return_net"],
            errors="coerce",
        ).fillna(0.0)
    return pd.to_numeric(
        df.get("authorized_return_net", pd.Series(index=df.index, dtype="float64")),
        errors="coerce",
    ).fillna(0.0)


def production_chart_authorized_exposure_series(df: pd.DataFrame) -> pd.Series:
    if "model_authorized_exposure_x" in df.columns:
        return pd.to_numeric(
            df["model_authorized_exposure_x"],
            errors="coerce",
        ).fillna(0.0)
    return pd.to_numeric(
        df.get("effective_market_exposure", pd.Series(index=df.index, dtype="float64")),
        errors="coerce",
    ).fillna(0.0)


def production_chart_real_account_equity_series(df: pd.DataFrame) -> pd.Series:
    if "real_account_index" in df.columns:
        return pd.to_numeric(df["real_account_index"], errors="coerce")
    return production_chart_authorized_equity_series(df)


def production_chart_real_account_return_series(df: pd.DataFrame) -> pd.Series:
    if "real_account_return_net" in df.columns:
        return pd.to_numeric(df["real_account_return_net"], errors="coerce").fillna(0.0)
    return production_chart_authorized_return_series(df)


def production_chart_real_account_exposure_series(df: pd.DataFrame) -> pd.Series:
    if "real_account_exposure_x" in df.columns:
        return pd.to_numeric(df["real_account_exposure_x"], errors="coerce").fillna(0.0)
    return production_chart_authorized_exposure_series(df)


def production_chart_live_strategy_equity_series(df: pd.DataFrame) -> pd.Series:
    if "live_strategy_index" in df.columns:
        return pd.to_numeric(df["live_strategy_index"], errors="coerce")
    if "strategy_execution_index" in df.columns:
        return pd.to_numeric(df["strategy_execution_index"], errors="coerce")
    return production_chart_authorized_equity_series(df)


def production_chart_live_strategy_return_series(df: pd.DataFrame) -> pd.Series:
    if "live_strategy_return_net" in df.columns:
        return pd.to_numeric(df["live_strategy_return_net"], errors="coerce").fillna(0.0)
    if "strategy_execution_return_net" in df.columns:
        return pd.to_numeric(df["strategy_execution_return_net"], errors="coerce").fillna(0.0)
    return production_chart_authorized_return_series(df)


def production_chart_live_strategy_exposure_series(df: pd.DataFrame) -> pd.Series:
    if "live_strategy_exposure_x" in df.columns:
        return pd.to_numeric(df["live_strategy_exposure_x"], errors="coerce").fillna(0.0)
    if "strategy_execution_exposure_x" in df.columns:
        return pd.to_numeric(df["strategy_execution_exposure_x"], errors="coerce").fillna(0.0)
    return production_chart_authorized_exposure_series(df)


def production_chart_strategy_execution_equity_series(df: pd.DataFrame) -> pd.Series:
    if "strategy_execution_index" in df.columns:
        return pd.to_numeric(df["strategy_execution_index"], errors="coerce")
    return production_chart_live_strategy_equity_series(df)


def production_chart_strategy_execution_return_series(df: pd.DataFrame) -> pd.Series:
    if "strategy_execution_return_net" in df.columns:
        return pd.to_numeric(df["strategy_execution_return_net"], errors="coerce").fillna(0.0)
    return production_chart_live_strategy_return_series(df)


def production_chart_strategy_execution_exposure_series(df: pd.DataFrame) -> pd.Series:
    if "strategy_execution_exposure_x" in df.columns:
        return pd.to_numeric(df["strategy_execution_exposure_x"], errors="coerce").fillna(0.0)
    return production_chart_live_strategy_exposure_series(df)


def production_chart_transition_cost_series(df: pd.DataFrame) -> pd.Series:
    if "model_transition_cost" in df.columns:
        return pd.to_numeric(
            df["model_transition_cost"],
            errors="coerce",
        ).fillna(0.0)
    transition_cost = pd.Series(0.0, index=df.index, dtype="float64")
    for column in ["fees_daily", "funding_daily", "borrow_cost_daily", "slippage_cost_daily"]:
        cost = pd.to_numeric(
            df.get(column, pd.Series(index=df.index, dtype="float64")),
            errors="coerce",
        ).fillna(0.0)
        transition_cost = transition_cost - cost
    return transition_cost


def production_chart_btc_index_series(df: pd.DataFrame) -> pd.Series:
    if "btc_index" in df.columns:
        return pd.to_numeric(df["btc_index"], errors="coerce")
    return pd.to_numeric(df.get("btc_baseline_equity", pd.Series(index=df.index, dtype="float64")), errors="coerce")


def production_chart_btc_return_series(df: pd.DataFrame) -> pd.Series:
    if {"real_account_return_net", "real_account_vs_btc_return"}.issubset(df.columns):
        real_return = pd.to_numeric(df["real_account_return_net"], errors="coerce").fillna(0.0)
        account_vs_btc = pd.to_numeric(df["real_account_vs_btc_return"], errors="coerce").fillna(0.0)
        return real_return - account_vs_btc
    return pd.to_numeric(df.get("btc_return", pd.Series(index=df.index, dtype="float64")), errors="coerce").fillna(0.0)


def production_chart_source_alignment_issues(timeseries_df: pd.DataFrame) -> list[str]:
    required_columns = [
        "date",
        "effective_market_exposure",
        "authorized_return_gross",
        "authorized_return_net",
        "authorized_equity",
        "asset_transition_day",
        "fees_daily",
        "funding_daily",
        "borrow_cost_daily",
        "slippage_cost_daily",
    ]
    missing_columns = sorted(column for column in required_columns if column not in timeseries_df.columns)
    if missing_columns:
        return [
            "production chart source alignment missing columns: "
            + ", ".join(missing_columns)
        ]

    exposure = production_chart_authorized_exposure_series(timeseries_df)
    gross = production_chart_authorized_gross_return_series(timeseries_df)
    net = production_chart_authorized_return_series(timeseries_df)
    equity = production_chart_authorized_equity_series(timeseries_df)
    transition_cost = production_chart_transition_cost_series(timeseries_df)
    issues: list[str] = []

    if equity.isna().any():
        bad_dates = timeseries_df.loc[equity.isna(), "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart authorized_equity contains non-numeric rows on dates: "
            + ", ".join(bad_dates)
        )
        return issues

    reconstructed_equity = (1.0 + net).cumprod()
    equity_mismatch_mask = (equity - reconstructed_equity).abs() > 1e-9
    if equity_mismatch_mask.any():
        bad_dates = timeseries_df.loc[equity_mismatch_mask, "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart red-line equity is not reconstructed from authorized_return_net on dates: "
            + ", ".join(bad_dates)
        )

    net_formula_mismatch_mask = ((gross + transition_cost) - net).abs() > 1e-9
    if net_formula_mismatch_mask.any():
        bad_dates = timeseries_df.loc[net_formula_mismatch_mask, "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart authorized_return_net is not explained by authorized_return_gross and explicit costs on dates: "
            + ", ".join(bad_dates)
        )

    zero_exposure_mask = exposure.abs().le(1e-12)
    zero_exposure_market_move_mask = zero_exposure_mask & gross.abs().gt(1e-12)
    if zero_exposure_market_move_mask.any():
        bad_dates = timeseries_df.loc[zero_exposure_market_move_mask, "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart zero-exposure rows have non-zero authorized_return_gross on dates: "
            + ", ".join(bad_dates)
        )

    zero_exposure_positive_net_mask = zero_exposure_mask & net.gt(1e-12)
    if zero_exposure_positive_net_mask.any():
        bad_dates = timeseries_df.loc[zero_exposure_positive_net_mask, "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart zero-exposure rows have positive authorized_return_net on dates: "
            + ", ".join(bad_dates)
        )

    zero_exposure_positive_transition_cost_mask = zero_exposure_mask & transition_cost.gt(1e-12)
    if zero_exposure_positive_transition_cost_mask.any():
        bad_dates = timeseries_df.loc[zero_exposure_positive_transition_cost_mask, "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart zero-exposure rows have positive explicit transition cost on dates: "
            + ", ".join(bad_dates)
        )

    zero_exposure_cost_mismatch_mask = (
        zero_exposure_mask
        & net.abs().gt(1e-12)
        & ((net - transition_cost).abs() > 1e-9)
    )
    if zero_exposure_cost_mismatch_mask.any():
        bad_dates = timeseries_df.loc[zero_exposure_cost_mismatch_mask, "date"].astype(str).head(5).tolist()
        issues.append(
            "production chart zero-exposure rows move without matching explicit transition cost on dates: "
            + ", ".join(bad_dates)
        )

    return issues


def _production_compare_float(
    expected: Any,
    actual: Any,
    *,
    field_name: str,
    abs_tol: float = 1e-9,
) -> None:
    expected_value = as_float(expected)
    actual_value = as_float(actual)
    if expected_value is None or actual_value is None:
        stop_for_production_homepage_block(
            f"{field_name} missing in production snapshot or timeseries"
        )
    if not math.isclose(expected_value, actual_value, abs_tol=abs_tol):
        stop_for_production_homepage_block(
            f"{field_name} mismatch between production snapshot and timeseries"
        )


def _production_compare_series(
    frame: pd.DataFrame,
    expected_column: str,
    actual_column: str,
    *,
    field_name: str,
    abs_tol: float = 1e-9,
) -> None:
    if expected_column not in frame.columns or actual_column not in frame.columns:
        stop_for_production_homepage_block(
            f"{field_name} columns are missing in production timeseries"
        )
    expected_series = pd.to_numeric(frame[expected_column], errors="coerce")
    actual_series = pd.to_numeric(frame[actual_column], errors="coerce")
    if expected_series.isna().any() or actual_series.isna().any():
        stop_for_production_homepage_block(
            f"{field_name} contains non-numeric values in production timeseries"
        )
    mismatch_mask = (expected_series - actual_series).abs() > abs_tol
    if mismatch_mask.any():
        bad_dates = frame.loc[mismatch_mask, "date"].astype(str).head(5).tolist()
        stop_for_production_homepage_block(
            f"{field_name} mismatch in production timeseries on dates: {', '.join(bad_dates)}"
        )


def validate_production_homepage_bundle(
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    quality: dict[str, Any],
    timeseries_df: pd.DataFrame,
) -> None:
    if str(quality.get("status") or "").strip().lower() != "passed":
        stop_for_production_homepage_block("quality report status is not passed")
    if str(get_nested_value(snapshot, "validation", "status") or "").strip().lower() != "passed":
        stop_for_production_homepage_block("snapshot validation status is not passed")
    if str(get_nested_value(diagnostics, "validation", "status") or "").strip().lower() != "passed":
        stop_for_production_homepage_block("diagnostics validation status is not passed")
    if str(snapshot.get("strategy_status") or "").strip().lower() != "ready":
        stop_for_production_homepage_block("strategy_status is not ready")
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, dict):
        stop_for_production_homepage_block("snapshot.metrics is missing")
    for metric_name in ("sharpe", "sortino"):
        if as_float(metrics.get(metric_name)) is None:
            stop_for_production_homepage_block(
                f"snapshot.metrics.{metric_name} is missing or non-numeric"
            )

    snapshot_day = str(snapshot.get("closed_day") or "").strip()
    diagnostics_day = str(diagnostics.get("closed_day") or "").strip()
    last_timeseries_day = str(timeseries_df.iloc[-1]["date"] or "").strip()
    if not snapshot_day or not diagnostics_day or not last_timeseries_day:
        stop_for_production_homepage_block("closed_day is missing")
    if snapshot_day != diagnostics_day or snapshot_day != last_timeseries_day:
        stop_for_production_homepage_block(
            "closed_day mismatch across snapshot, diagnostics, and timeseries"
        )

    snapshot_strategy_id = str(snapshot.get("strategy_id") or "").strip()
    diagnostics_strategy_id = str(diagnostics.get("strategy_id") or "").strip()
    timeseries_strategy_id = str(timeseries_df.iloc[-1]["strategy_id"] or "").strip()
    if not snapshot_strategy_id or snapshot_strategy_id != diagnostics_strategy_id or snapshot_strategy_id != timeseries_strategy_id:
        stop_for_production_homepage_block("strategy_id mismatch across production artifacts")

    snapshot_strategy_version = str(snapshot.get("strategy_version") or "").strip()
    diagnostics_strategy_version = str(diagnostics.get("strategy_version") or "").strip()
    timeseries_strategy_version = str(timeseries_df.iloc[-1]["strategy_version"] or "").strip()
    if (
        not snapshot_strategy_version
        or snapshot_strategy_version != diagnostics_strategy_version
        or snapshot_strategy_version != timeseries_strategy_version
    ):
        stop_for_production_homepage_block("strategy_version mismatch across production artifacts")

    last_row = sanitize_row_dict(timeseries_df.iloc[-1].to_dict())
    if str(last_row.get("candidate_asset") or "").strip().upper() != str(snapshot.get("candidate_asset") or "").strip().upper():
        stop_for_production_homepage_block("candidate asset mismatch between snapshot and timeseries")
    if str(last_row.get("actual_held_asset") or "").strip().upper() != str(snapshot.get("actual_held_asset") or "").strip().upper():
        stop_for_production_homepage_block("actual held asset mismatch between snapshot and timeseries")
    if str(last_row.get("authorized_tradable_asset") or "").strip().upper() != str(snapshot.get("authorized_tradable_asset") or "").strip().upper():
        stop_for_production_homepage_block("authorized tradable asset mismatch between snapshot and timeseries")
    if str(last_row.get("market_state") or "").strip().upper() != str(snapshot.get("market_state") or "").strip().upper():
        stop_for_production_homepage_block("market_state mismatch between snapshot and timeseries")
    if str(last_row.get("held_asset") or "").strip().upper() != str(snapshot.get("current_asset") or "").strip().upper():
        stop_for_production_homepage_block("current asset mismatch between snapshot and timeseries")
    if str(last_row.get("regime") or "").strip().upper() != str(snapshot.get("current_regime") or "").strip().upper():
        stop_for_production_homepage_block("current regime mismatch between snapshot and timeseries")
    if str(last_row.get("execution_state") or "").strip().upper() != str(snapshot.get("execution_state") or "").strip().upper():
        stop_for_production_homepage_block("execution state mismatch between snapshot and timeseries")
    if str(last_row.get("trend_state") or "").strip() != str(snapshot.get("trend_state") or "").strip():
        stop_for_production_homepage_block("trend state mismatch between snapshot and timeseries")
    _production_compare_float(
        snapshot.get("current_exposure"),
        last_row.get("exposure"),
        field_name="current_exposure",
    )
    _production_compare_float(
        snapshot.get("effective_market_exposure"),
        last_row.get("effective_market_exposure"),
        field_name="effective_market_exposure",
    )
    _production_compare_series(
        timeseries_df,
        "authorized_return_gross",
        "return_gross",
        field_name="primary gross return semantics",
    )
    _production_compare_series(
        timeseries_df,
        "authorized_return_net",
        "return_net",
        field_name="primary net return semantics",
    )
    _production_compare_series(
        timeseries_df,
        "authorized_equity",
        "equity",
        field_name="primary equity semantics",
    )
    chart_source_alignment_issues = production_chart_source_alignment_issues(timeseries_df)
    if chart_source_alignment_issues:
        stop_for_production_homepage_block(chart_source_alignment_issues[0])
    btc_close_series = pd.to_numeric(timeseries_df["btc_close"], errors="coerce")
    btc_return_series = pd.to_numeric(timeseries_df["btc_return"], errors="coerce")
    btc_baseline_equity_series = pd.to_numeric(
        timeseries_df["btc_baseline_equity"],
        errors="coerce",
    )
    btc_baseline_index_series = pd.to_numeric(
        timeseries_df["btc_baseline_index"],
        errors="coerce",
    )
    if (
        btc_close_series.isna().any()
        or btc_return_series.isna().any()
        or btc_baseline_equity_series.isna().any()
        or btc_baseline_index_series.isna().any()
    ):
        stop_for_production_homepage_block("BTC baseline fields contain non-numeric values")
    if (btc_close_series <= 0).any():
        stop_for_production_homepage_block("BTC baseline close must stay strictly positive")
    reconstructed_btc_return_series = btc_close_series.pct_change().fillna(0.0)
    btc_return_mismatch = (
        reconstructed_btc_return_series - btc_return_series
    ).abs() > 1e-9
    if btc_return_mismatch.any():
        bad_dates = timeseries_df.loc[btc_return_mismatch, "date"].astype(str).head(5).tolist()
        stop_for_production_homepage_block(
            "BTC baseline return mismatch in production timeseries on dates: "
            + ", ".join(bad_dates)
        )
    btc_equity_mismatch = (
        (1.0 + btc_return_series).cumprod() - btc_baseline_equity_series
    ).abs() > 1e-9
    if btc_equity_mismatch.any():
        bad_dates = timeseries_df.loc[btc_equity_mismatch, "date"].astype(str).head(5).tolist()
        stop_for_production_homepage_block(
            "BTC baseline equity mismatch in production timeseries on dates: "
            + ", ".join(bad_dates)
        )
    btc_index_mismatch = (
        (btc_baseline_equity_series * 100.0) - btc_baseline_index_series
    ).abs() > 1e-9
    if btc_index_mismatch.any():
        bad_dates = timeseries_df.loc[btc_index_mismatch, "date"].astype(str).head(5).tolist()
        stop_for_production_homepage_block(
            "BTC baseline index mismatch in production timeseries on dates: "
            + ", ".join(bad_dates)
        )
    _production_compare_float(
        snapshot.get("model_candidate_exposure"),
        last_row.get("model_candidate_exposure"),
        field_name="model_candidate_exposure",
    )
    _production_compare_float(
        snapshot.get("trend_score"),
        last_row.get("trend_score"),
        field_name="trend_score",
        abs_tol=1e-6,
    )
    if as_bool(last_row.get("trend_permission_active")) != as_bool(snapshot.get("trend_permission_active")):
        stop_for_production_homepage_block("trend_permission_active mismatch between snapshot and timeseries")

    trend_permission_active = as_bool(snapshot.get("trend_permission_active")) is True
    current_asset = str(snapshot.get("current_asset") or "").strip().upper()
    candidate_asset = str(snapshot.get("candidate_asset") or "").strip().upper()
    current_exposure = as_float(snapshot.get("current_exposure")) or 0.0
    execution_target_asset = str(get_nested_value(snapshot, "execution_intent", "target_asset") or "").strip().upper()
    execution_target_exposure = as_float(get_nested_value(snapshot, "execution_intent", "target_exposure")) or 0.0
    if not trend_permission_active:
        if current_asset not in {"CASH"}:
            stop_for_production_homepage_block("trend_permission_active=false but current_asset is not CASH")
        if current_exposure > 1e-9:
            stop_for_production_homepage_block("trend_permission_active=false but current_exposure is above zero")
        if execution_target_asset not in {"CASH"} or execution_target_exposure > 1e-9:
            stop_for_production_homepage_block("trend_permission_active=false but execution target is not CASH/0.0")
        if candidate_asset == current_asset and candidate_asset not in {"", "CASH"}:
            stop_for_production_homepage_block("candidate asset is mixed into current asset while trend permission is inactive")
    elif current_exposure <= 1e-9:
        stop_for_production_homepage_block("trend_permission_active=true but current_exposure is zero")

    if as_bool(last_row.get("source_validated")) is not True:
        stop_for_production_homepage_block("latest timeseries row is not source_validated")
    if str(get_nested_value(diagnostics, "current_data_health_summary", "status") or "").strip().lower() not in {"", "passed"}:
        stop_for_production_homepage_block("diagnostics current_data_health_summary status is not passed")


def load_production_homepage_bundle() -> dict[str, Any]:
    snapshot = load_required_production_payload(
        PRODUCTION_SNAPSHOT_PATH,
        "current_strategy_snapshot",
        context="production snapshot",
    )
    diagnostics = load_required_production_payload(
        PRODUCTION_DIAGNOSTICS_PATH,
        "current_strategy_diagnostics",
        context="production diagnostics",
    )
    quality = load_required_production_payload(
        PRODUCTION_QUALITY_PATH,
        "current_strategy_snapshot_quality",
        context="production quality",
    )
    timeseries_df = load_production_timeseries_frame(PRODUCTION_TIMESERIES_PATH)
    validate_production_homepage_bundle(snapshot, diagnostics, quality, timeseries_df)
    return {
        "snapshot": snapshot,
        "diagnostics": diagnostics,
        "quality": quality,
        "timeseries": timeseries_df,
    }


def load_required_authority_payload(path: Path, expected_type: str) -> dict:
    payload = load_json_optional(path)
    if not payload:
        st.error(f"{t(st.session_state.get('lang', 'sk'), 'load_failed')}: missing {path}")
        st.stop()
    if payload.get("artifact_type") != expected_type:
        st.error(
            f"{t(st.session_state.get('lang', 'sk'), 'load_failed')}: "
            f"{path} is not {expected_type}"
        )
        st.stop()
    return payload


def load_optional_authority_payload(path: Path, expected_type: str) -> dict:
    payload = load_json_optional(path)
    if not payload:
        return {}
    if payload.get("artifact_type") != expected_type:
        # Attempt status is a non-blocking overlay for the public homepage.
        return {}
    return payload


def require_snapshot_payload(
    payload: dict,
    expected_type: str,
    source_path: Path,
) -> dict:
    if not payload:
        st.error(
            f"{t(st.session_state.get('lang', 'sk'), 'load_failed')}: "
            f"missing nested {expected_type} in {source_path}"
        )
        st.stop()
    if payload.get("snapshot_type") != expected_type:
        st.error(
            f"{t(st.session_state.get('lang', 'sk'), 'load_failed')}: "
            f"{source_path} nested payload is not {expected_type}"
        )
        st.stop()
    return payload


FRESHNESS_SUMMARY_TEXT = {
    "current": "Current: the latest update is aligned with the latest closed UTC day.",
    "stale": "Stale: the latest validated state is behind the latest closed UTC day.",
    "refresh_in_progress": "Refresh in progress: the latest update is still running.",
    "refresh_failed": "Refresh failed: the latest update failed.",
    "missing_authority_artifact": "Refresh status is unavailable.",
}


def _derive_authority_currentness(
    latest_successful_snapshot: dict,
    latest_attempt_status: dict,
) -> tuple[str, str, Path, str]:
    preferred_payload, preferred_source_path, preferred_source_type = select_preferred_authority_payload(
        latest_successful_snapshot,
        latest_attempt_status,
    )
    alternate_payload = (
        latest_attempt_status
        if preferred_source_path == AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH
        else latest_successful_snapshot
    )
    selected_payload = preferred_payload if isinstance(preferred_payload, dict) else {}
    fallback_payload = alternate_payload if isinstance(alternate_payload, dict) else {}

    def first_present(*values: Any) -> str | None:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    attempt_status = first_present(
        selected_payload.get("latest_authoritative_attempt_status"),
        fallback_payload.get("latest_authoritative_attempt_status"),
    )
    normalized_attempt_status = str(attempt_status or "").strip().lower()

    if normalized_attempt_status == "in_progress":
        return (
            "refresh_in_progress",
            FRESHNESS_SUMMARY_TEXT["refresh_in_progress"],
            preferred_source_path,
            preferred_source_type,
        )

    if normalized_attempt_status == "failed":
        attempt_error = first_present(
            selected_payload.get("latest_authoritative_attempt_error"),
            fallback_payload.get("latest_authoritative_attempt_error"),
        )
        reason = FRESHNESS_SUMMARY_TEXT["refresh_failed"]
        if attempt_error:
            reason = f"{reason} error={attempt_error}."
        return "refresh_failed", reason, preferred_source_path, preferred_source_type

    target_closed_day_utc = first_present(
        selected_payload.get("target_closed_day_utc"),
        fallback_payload.get("target_closed_day_utc"),
    )
    strategy_artifact_closed_day_utc = first_present(
        selected_payload.get("strategy_artifact_closed_day_utc"),
        fallback_payload.get("strategy_artifact_closed_day_utc"),
    )

    if target_closed_day_utc and strategy_artifact_closed_day_utc:
        if target_closed_day_utc == strategy_artifact_closed_day_utc:
            return (
                "current",
                (
                    "Current: target closed UTC day "
                    f"{target_closed_day_utc} matches strategy closed UTC day "
                    f"{strategy_artifact_closed_day_utc}."
                ),
                preferred_source_path,
                preferred_source_type,
            )
        return (
            "stale",
            (
                "Stale: target closed UTC day "
                f"{target_closed_day_utc} does not match strategy closed UTC day "
                f"{strategy_artifact_closed_day_utc}."
            ),
            preferred_source_path,
            preferred_source_type,
        )

    if target_closed_day_utc:
        return (
            "stale",
            (
                "Stale: target closed UTC day "
                f"{target_closed_day_utc} is present but strategy closed UTC day is missing."
            ),
            preferred_source_path,
            preferred_source_type,
        )

    if normalized_attempt_status == "success":
        return (
            "stale",
            "Stale: the latest update succeeded but target day fields are missing.",
            preferred_source_path,
            preferred_source_type,
        )

    return (
        "missing_authority_artifact",
        FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"],
        preferred_source_path,
        preferred_source_type,
    )


def build_missing_runtime_snapshot(path: Path) -> dict:
    missing_freshness = {
        "latest_refresh_run_id": None,
        "latest_refresh_run_status": None,
        "latest_successful_refresh_run_id": None,
        "refresh_currentness_state": "missing_authority_artifact",
        "refresh_currentness_reason_code": "authority_artifact_missing",
        "refresh_currentness_reason": FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"],
        "freshness_state": "missing_authority_artifact",
        "freshness_detail_code": "authority_artifact_missing",
        "freshness_summary_text": FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"],
        "freshness_detail_text": FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"],
        "refresh_run_id": None,
        "refresh_success": None,
        "refresh_status": None,
        "refresh_finished_at_utc": None,
        "refresh_manifest_path": None,
        "latest_strategy_artifact_date": None,
        "latest_successful_refresh_runtime_utc": None,
        "latest_trend_calculation_date": None,
        "latest_wallet_sync_utc": None,
        "latest_available_closed_utc_date": None,
    }
    missing_runtime_table_snapshot = {
        "last_pi_update_utc": None,
        "last_pc_refresh_utc": None,
        "last_refresh_status": None,
        "last_refresh_run_id": None,
        "last_wallet_sync_utc": None,
        "currentness_state": "missing_authority_artifact",
        "currentness_reason": FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"],
        "source_metadata": {
            "last_pi_update_utc": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
                "source_field": "generated_at_utc",
            },
            "last_refresh_status": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
                "source_field": "latest_authoritative_attempt_status",
            },
            "last_refresh_run_id": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
                "source_field": "run_id",
            },
            "last_wallet_sync_utc": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
                "source_field": "authority_wallet_sync_utc|authority_account_snapshot_as_of_utc",
            },
            "currentness_state": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
                "source_field": "currentness_status",
            },
            "currentness_reason": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
                "source_field": "currentness_reason",
            },
        },
        "evaluated_at_utc": None,
    }
    return {
        "snapshot_type": "app_runtime_snapshot",
        "schema_version": 2,
        "app_export_generated_at_utc": None,
        "account_observability_contract": {"enabled": False},
        "dashboard_public_status": {},
        "strategy_freshness": missing_freshness,
        "runtime_table_snapshot": missing_runtime_table_snapshot,
        **missing_freshness,
        "source_metadata": {
            "authority_latest_attempt_status": {
                "path": str(path),
                "exists": False,
                "source_type": "authority_latest_attempt_status",
            },
        },
    }


def load_runtime_snapshot_for_app(payload: dict, path: Path) -> dict:
    if not payload or payload.get("snapshot_type") != "app_runtime_snapshot":
        return build_missing_runtime_snapshot(path)
    return payload


def select_preferred_account_runtime_snapshot(authority_runtime_snapshot: dict) -> dict:
    local_runtime_snapshot = load_runtime_snapshot_for_app(
        load_json_optional(LOCAL_APP_RUNTIME_SNAPSHOT_PATH),
        LOCAL_APP_RUNTIME_SNAPSHOT_PATH,
    )
    authority_account_as_of = parse_iso_datetime_optional(
        authority_runtime_snapshot.get("account_snapshot_as_of_utc")
    )
    local_account_as_of = parse_iso_datetime_optional(
        local_runtime_snapshot.get("account_snapshot_as_of_utc")
    )
    if local_account_as_of and (
        authority_account_as_of is None or local_account_as_of > authority_account_as_of
    ):
        return local_runtime_snapshot

    authority_generated_at = parse_iso_datetime_optional(
        authority_runtime_snapshot.get("app_runtime_snapshot_generated_at_utc")
    )
    local_generated_at = parse_iso_datetime_optional(
        local_runtime_snapshot.get("app_runtime_snapshot_generated_at_utc")
    )
    local_account_summary = local_runtime_snapshot.get("account_snapshot_summary")
    if (
        local_generated_at
        and (authority_generated_at is None or local_generated_at > authority_generated_at)
        and isinstance(local_account_summary, dict)
        and local_account_summary
    ):
        return local_runtime_snapshot
    return authority_runtime_snapshot


def load_dashboard_public_status_for_app(
    runtime_snapshot: dict[str, Any],
    production_snapshot: dict[str, Any],
) -> dict[str, Any]:
    target_closed_day = str(production_snapshot.get("closed_day") or "").strip()
    candidates: list[tuple[datetime, int, dict[str, Any]]] = []
    payload_candidates = [
        (
            dict(runtime_snapshot.get("dashboard_public_status") or {}),
            0,
        ),
        (
            load_json_optional(LOCAL_DASHBOARD_PUBLIC_STATUS_PATH),
            1,
        ),
    ]
    required_sections = {
        "real_account",
        "execution",
        "model_signal",
        "model_performance",
        "data_health",
        "live_market_state",
        "public_labels_sk",
    }

    for payload, source_priority in payload_candidates:
        if not isinstance(payload, dict):
            continue
        if int(payload.get("schema_version") or 0) != 1:
            continue
        if not required_sections.issubset(payload.keys()):
            continue
        closed_day = str(payload.get("closed_day") or "").strip()
        if target_closed_day and closed_day and closed_day != target_closed_day:
            continue
        generated_at = parse_iso_datetime_optional(payload.get("generated_at_utc")) or datetime(
            1970,
            1,
            1,
            tzinfo=timezone.utc,
        )
        candidates.append((generated_at, source_priority, payload))

    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def resolve_dashboard_public_status_state(
    dashboard_public_status: dict[str, Any],
    lang: str,
) -> dict[str, Any]:
    if not isinstance(dashboard_public_status, dict) or int(dashboard_public_status.get("schema_version") or 0) != 1:
        return {}

    real_account = (
        dashboard_public_status.get("real_account")
        if isinstance(dashboard_public_status.get("real_account"), dict)
        else {}
    )
    execution = (
        dashboard_public_status.get("execution")
        if isinstance(dashboard_public_status.get("execution"), dict)
        else {}
    )
    model_signal = (
        dashboard_public_status.get("model_signal")
        if isinstance(dashboard_public_status.get("model_signal"), dict)
        else {}
    )
    model_performance = (
        dashboard_public_status.get("model_performance")
        if isinstance(dashboard_public_status.get("model_performance"), dict)
        else {}
    )
    live_market_state = (
        dashboard_public_status.get("live_market_state")
        if isinstance(dashboard_public_status.get("live_market_state"), dict)
        else {}
    )
    public_labels_sk = (
        dashboard_public_status.get("public_labels_sk")
        if isinstance(dashboard_public_status.get("public_labels_sk"), dict)
        else {}
    )

    real_asset = str(real_account.get("asset") or "CASH").strip().upper() or "CASH"
    real_exposure_value = as_float(real_account.get("exposure_x"))
    if real_exposure_value is None:
        real_exposure_value = 0.0
    in_market = as_bool(real_account.get("in_market")) is True
    state_text = (
        str(real_account.get("position_label_sk") or "").strip()
        if lang == "sk"
        else t(lang, "production_state_in_market")
        if in_market
        else t(lang, "production_state_out_of_market")
    )
    if not state_text:
        state_text = (
            t(lang, "production_state_in_market")
            if in_market
            else t(lang, "production_state_out_of_market")
        )
    exposure_text = f"{real_exposure_value:.2f}x"
    gate_status = str(execution.get("gate_status") or "").strip().lower()
    would_place_real_order = as_bool(execution.get("would_place_real_order"))
    ordering_blocked = gate_status == "blocked" or would_place_real_order is False
    subtitle = (
        "CASH | Odoslanie obchodu blokovane"
        if lang == "sk" and ordering_blocked
        else "CASH | Podla uctu a vykonavacich kontrol"
        if lang == "sk"
        else "CASH | Order placement blocked"
        if ordering_blocked
        else "CASH | Based on account and execution checks"
    )
    if in_market:
        subtitle = (
            f"Otvorena pozicia: {real_asset}"
            if lang == "sk"
            else f"Open position: {real_asset}"
        )

    model_exposure_value = as_float(model_signal.get("exposure_x"))
    model_exposure_text = (
        f"{model_exposure_value:.2f}x"
        if model_exposure_value is not None
        else t(lang, "na")
    )

    return {
        "public_labels_sk": public_labels_sk,
        "real_account_exposure_state": {
            "is_out_of_market": not in_market,
            "asset": real_asset,
            "exposure": real_exposure_value,
            "exposure_text": exposure_text,
            "state_text": state_text,
            "value": f"{state_text} / {exposure_text}",
            "subtitle": subtitle,
            "target_asset": str(execution.get("target_asset") or real_asset).strip().upper() or real_asset,
            "gate_status": gate_status,
            "would_place_real_order": would_place_real_order,
            "label_sk": str(public_labels_sk.get("real_account") or "Reálny účet").strip(),
        },
        "model_signal_state": {
            "preferred_asset": normalize_public_asset_code(model_signal.get("preferred_asset")),
            "exposure_x": model_exposure_value,
            "exposure_text": model_exposure_text,
            "label_sk": str(model_signal.get("label_sk") or public_labels_sk.get("model_signal") or "Modelový signál").strip(),
            "not_real_wallet_exposure": as_bool(model_signal.get("not_real_wallet_exposure")) is not False,
        },
        "model_performance_state": {
            "account_24h_pct": as_float(model_performance.get("account_24h_pct")),
            "btc_24h_pct": as_float(model_performance.get("btc_24h_pct")),
            "account_vs_btc_24h_pct": as_float(model_performance.get("account_vs_btc_24h_pct")),
            "public_average_annual_growth_pct": as_float(model_performance.get("public_average_annual_growth_pct")),
            "since_etf_start_cagr_pct": as_float(model_performance.get("since_etf_start_cagr_pct")),
            "since2025_cagr_pct": as_float(model_performance.get("since2025_cagr_pct")),
            "btc_24h_pct_source_label": (
                "closed_day_snapshot"
                if as_bool(live_market_state.get("btc_24h_pct_snapshot_is_not_live")) is True
                else str(live_market_state.get("btc_24h_pct_source") or "").strip()
            ),
        },
    }


def build_authority_runtime_table_snapshot(
    latest_successful_snapshot: dict,
    latest_attempt_status: dict,
) -> dict:
    primary_payload, source_path, source_type = select_preferred_authority_payload(
        latest_successful_snapshot,
        latest_attempt_status,
    )
    secondary_payload = (
        latest_attempt_status
        if source_path == AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH
        else latest_successful_snapshot
    )
    primary_payload = primary_payload if isinstance(primary_payload, dict) else {}
    secondary_payload = secondary_payload if isinstance(secondary_payload, dict) else {}
    authority_generated_at_utc = (
        primary_payload.get("generated_at_utc")
        or primary_payload.get("refresh_finished_at_utc")
        or secondary_payload.get("generated_at_utc")
        or secondary_payload.get("refresh_finished_at_utc")
    )
    authority_run_id = primary_payload.get("run_id") or secondary_payload.get("run_id")
    authority_attempt_status = (
        str(
            primary_payload.get("latest_authoritative_attempt_status")
            or secondary_payload.get("latest_authoritative_attempt_status")
            or ""
        ).strip().lower()
        or None
    )
    (
        authority_currentness_state,
        authority_currentness_reason,
        currentness_source_path,
        currentness_source_type,
    ) = _derive_authority_currentness(
        latest_successful_snapshot,
        latest_attempt_status,
    )
    wallet_sync_utc = (
        primary_payload.get("authority_wallet_sync_utc")
        or primary_payload.get("authority_account_snapshot_as_of_utc")
    )
    wallet_source_path = source_path
    wallet_source_type = source_type
    if not wallet_sync_utc:
        wallet_sync_utc = (
            secondary_payload.get("authority_wallet_sync_utc")
            or secondary_payload.get("authority_account_snapshot_as_of_utc")
        )
        if source_path == AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH:
            wallet_source_path = AUTHORITY_LATEST_ATTEMPT_STATUS_PATH
            wallet_source_type = ATTEMPT_STATUS_ARTIFACT_TYPE
        else:
            wallet_source_path = AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH
            wallet_source_type = SUCCESS_SNAPSHOT_ARTIFACT_TYPE
    return {
        "last_pi_update_utc": authority_generated_at_utc,
        "last_pc_refresh_utc": None,
        "last_refresh_status": authority_attempt_status,
        "last_refresh_run_id": authority_run_id,
        "last_wallet_sync_utc": wallet_sync_utc,
        "currentness_state": authority_currentness_state,
        "currentness_reason": authority_currentness_reason,
        "source_metadata": {
            "last_pi_update_utc": {
                "path": str(source_path),
                "exists": source_path.exists(),
                "source_type": source_type,
                "source_field": "generated_at_utc|refresh_finished_at_utc",
            },
            "last_refresh_status": {
                "path": str(source_path),
                "exists": source_path.exists(),
                "source_type": source_type,
                "source_field": "latest_authoritative_attempt_status",
            },
            "last_refresh_run_id": {
                "path": str(source_path),
                "exists": source_path.exists(),
                "source_type": source_type,
                "source_field": "run_id",
            },
            "last_wallet_sync_utc": {
                "path": str(wallet_source_path),
                "exists": wallet_source_path.exists(),
                "source_type": wallet_source_type,
                "source_field": "authority_wallet_sync_utc|authority_account_snapshot_as_of_utc",
            },
            "currentness_state": {
                "path": str(currentness_source_path),
                "exists": currentness_source_path.exists(),
                "source_type": currentness_source_type,
                "source_field": "target_closed_day_utc|strategy_artifact_closed_day_utc|latest_authoritative_attempt_status",
            },
            "currentness_reason": {
                "path": str(currentness_source_path),
                "exists": currentness_source_path.exists(),
                "source_type": currentness_source_type,
                "source_field": "target_closed_day_utc|strategy_artifact_closed_day_utc|latest_authoritative_attempt_status|latest_authoritative_attempt_error",
            },
        },
        "evaluated_at_utc": authority_generated_at_utc,
    }


def build_authority_verification_rows(
    runtime_snapshot: dict,
    runtime_source_path: Path,
    runtime_authority_payload: dict,
) -> list[dict[str, Any]]:
    authority_source_path = str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH)
    if runtime_source_path != AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH:
        authority_source_path = (
            f"homepage={AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH} | "
            f"runtime={runtime_source_path}"
        )

    refresh_success = runtime_snapshot.get("refresh_success")
    if refresh_success is None:
        refresh_success = (
            str(runtime_authority_payload.get("latest_authoritative_attempt_status") or "").strip().lower()
            == "success"
        )

    return [
        {
            "Pole": "authority source path",
            "Hodnota": authority_source_path,
        },
        {
            "Pole": "run_id",
            "Hodnota": safe_text_value(
                runtime_authority_payload.get("run_id") or runtime_snapshot.get("refresh_run_id"),
                lang="sk",
            ),
        },
        {
            "Pole": "generated_at_utc",
            "Hodnota": safe_text_value(
                runtime_authority_payload.get("generated_at_utc")
                or runtime_authority_payload.get("refresh_finished_at_utc"),
                lang="sk",
            ),
        },
        {
            "Pole": "latest_available_closed_utc_date",
            "Hodnota": safe_text_value(
                runtime_snapshot.get("latest_available_closed_utc_date")
                or runtime_authority_payload.get("latest_available_closed_utc_day"),
                lang="sk",
            ),
        },
        {
            "Pole": "latest_strategy_artifact_date",
            "Hodnota": safe_text_value(
                runtime_snapshot.get("latest_strategy_artifact_date")
                or runtime_authority_payload.get("strategy_artifact_closed_day_utc"),
                lang="sk",
            ),
        },
        {
            "Pole": "refresh_status",
            "Hodnota": safe_text_value(
                runtime_snapshot.get("refresh_status")
                or runtime_authority_payload.get("latest_authoritative_attempt_status"),
                lang="sk",
            ),
        },
        {
            "Pole": "refresh_success",
            "Hodnota": str(bool(refresh_success)).lower() if refresh_success is not None else t("sk", "na"),
        },
    ]


def values_match_for_integrity(left: Any, right: Any) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text and not right_text:
        return True

    left_number = as_float(left)
    right_number = as_float(right)
    if left_number is not None and right_number is not None:
        return math.isclose(left_number, right_number, rel_tol=1e-9, abs_tol=1e-9)

    left_bool = as_bool(left)
    right_bool = as_bool(right)
    if left_bool is not None and right_bool is not None:
        return left_bool == right_bool

    return left_text == right_text


def build_homepage_authority_integrity_findings(
    product_snapshot: dict,
    runtime_snapshot: dict,
    csv_live_public_state: dict[str, Any],
    csv_metrics_row: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    authority_live_public_state = dict(product_snapshot.get("live_public_state") or {})
    authority_main_metrics = dict(product_snapshot.get("main_strategy_metrics") or {})

    authority_strategy_day = str(product_snapshot.get("strategy_last_closed_day") or "").strip()
    csv_strategy_day = str(csv_live_public_state.get("date") or "").strip()[:10]
    if authority_strategy_day and csv_strategy_day and authority_strategy_day != csv_strategy_day:
        findings.append(
            "Mismatch: homepage paper posledny den je "
            f"{csv_strategy_day}, ale authority strategy_last_closed_day je {authority_strategy_day}."
        )

    authority_closed_day = str(runtime_snapshot.get("latest_available_closed_utc_date") or "").strip()
    if authority_strategy_day and authority_closed_day and authority_strategy_day != authority_closed_day:
        findings.append(
            "Mismatch: authority strategy_last_closed_day je "
            f"{authority_strategy_day}, ale authority latest_available_closed_utc_date je {authority_closed_day}."
        )

    live_field_labels = {
        "portfolio_held_asset": "portfolio_held_asset",
        "held_asset_public": "held_asset_public",
        "trend_state_label": "trend_state_label",
        "trend_score": "trend_score",
        "buy_threshold": "buy_threshold",
        "cash_day": "cash_day",
    }
    for field, label in live_field_labels.items():
        authority_value = authority_live_public_state.get(field)
        csv_value = csv_live_public_state.get(field)
        if authority_value is None and csv_value is None:
            continue
        if not values_match_for_integrity(authority_value, csv_value):
            findings.append(
                f"Mismatch: homepage {label} je {csv_value!r}, ale authority JSON ma {authority_value!r}."
            )

    metric_labels = {
        "total_return_pct": "total_return_pct",
        "cagr_pct": "cagr_pct",
        "max_drawdown_pct": "max_drawdown_pct",
        "since2023_cagr_pct": "since2023_cagr_pct",
        "since2025_cagr_pct": "since2025_cagr_pct",
        "sharpe": "sharpe",
        "sortino": "sortino",
        "switch_count": "switch_count",
        "cash_days_pct": "cash_days_pct",
        "btc_days_pct": "btc_days_pct",
    }
    for field, label in metric_labels.items():
        authority_value = authority_main_metrics.get(field)
        csv_value = csv_metrics_row.get(field)
        if authority_value is None and csv_value is None:
            continue
        if not values_match_for_integrity(authority_value, csv_value):
            findings.append(
                f"Mismatch: homepage {label} je {csv_value!r}, ale authority JSON ma {authority_value!r}."
            )

    return findings


def build_selector_config_from_snapshot(product_snapshot: dict, runtime_snapshot: dict) -> dict:
    main_key = str(product_snapshot.get("main_strategy_model") or "").strip()
    reference_key = str(product_snapshot.get("reference_strategy_model") or "").strip()
    chart_paths = product_snapshot.get("chart_source_paths") if isinstance(product_snapshot.get("chart_source_paths"), dict) else {}
    source_metadata = product_snapshot.get("source_metadata") if isinstance(product_snapshot.get("source_metadata"), dict) else {}
    trend_summary_source = (
        source_metadata.get("trend_barometer_summary")
        if isinstance(source_metadata.get("trend_barometer_summary"), dict)
        else {}
    )
    trend_summary_snapshot = (
        product_snapshot.get("trend_barometer_summary")
        if isinstance(product_snapshot.get("trend_barometer_summary"), dict)
        else {}
    )
    model_sources: dict[str, dict[str, str]] = {}
    if main_key:
        model_sources[main_key] = {"paper_path": str(chart_paths.get("main_strategy") or "").strip()}
    if reference_key and chart_paths.get("reference_strategy"):
        model_sources[reference_key] = {"paper_path": str(chart_paths.get("reference_strategy") or "").strip()}

    return {
        "product_name": product_snapshot.get("product_name") or APP_SELECTOR_DEFAULTS["product_name"],
        "main_model_key": main_key,
        "reference_model_key": reference_key,
        "benchmark_label": product_snapshot.get("benchmark") or "BTC",
        "compare_model_keys": [main_key] if main_key else [],
        "display_names": product_snapshot.get("display_names") or {},
        "model_sources": model_sources,
        "trend_barometer_source": {
            "live_status_path": trend_summary_source.get("path"),
            "history_path": product_snapshot.get("trend_history_source_path"),
            "model_key": str(trend_summary_snapshot.get("model") or "phase66g_production_soft_filters").strip(),
            "authority_live_summary": dict(trend_summary_snapshot),
        },
        "app_live_mode_contract": {"current": product_snapshot.get("live_public_state") or {}},
        "account_observability_contract": {
            "current": runtime_snapshot.get("account_observability_contract") or {}
        },
    }


def load_single_csv_row(path: Path, *, context: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
    except Exception as exc:
        raise ValueError(f"{context}: failed reading CSV {path}: {exc}") from exc

    if len(rows) != 1:
        raise ValueError(f"{context}: expected exactly 1 row in {path}, got {len(rows)}")

    return {str(key).strip(): value for key, value in rows[0].items()}


def sanitize_snapshot_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def sanitize_row_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip(): sanitize_snapshot_value(value) for key, value in row.items()}


def get_current_account_observability_contract(selector_cfg: dict) -> dict:
    contract = selector_cfg.get("account_observability_contract") or {}
    if not isinstance(contract, dict):
        return {}
    current = contract.get("current") or {}
    if not isinstance(current, dict):
        return {}
    return dict(current)


def get_git_commit_marker() -> str:
    for env_key in [
        "GIT_COMMIT",
        "GIT_SHA",
        "COMMIT_SHA",
        "STREAMLIT_GIT_COMMIT",
        "RENDER_GIT_COMMIT",
        "GITHUB_SHA",
        "HEROKU_SLUG_COMMIT",
    ]:
        value = str(os.environ.get(env_key) or "").strip()
        if value:
            return value

    git_dir = ROOT / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return "unknown"

    try:
        head_text = head_path.read_text(encoding="utf-8").strip()
        if not head_text:
            return "unknown"
        if not head_text.startswith("ref:"):
            return head_text
        ref_name = head_text.split(":", 1)[1].strip()
        ref_path = git_dir / ref_name
        if ref_path.exists():
            ref_text = ref_path.read_text(encoding="utf-8").strip()
            return ref_text or "unknown"
    except OSError:
        return "unknown"

    return "unknown"


def first_present_value(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def get_nested_value(payload: dict | None, *keys):
    current = payload if isinstance(payload, dict) else {}
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def get_nested_dict(payload: dict | None, *keys) -> dict:
    nested = get_nested_value(payload, *keys)
    return nested if isinstance(nested, dict) else {}


def control_bool_text(value) -> str:
    parsed = as_bool(value)
    if parsed is None:
        return "Nedostupne"
    return "Ano" if parsed else "Nie"


def format_date_text(value, lang: str = "sk") -> str:
    if value is None:
        return t(lang, "na")

    parsed = None
    text = str(value).strip()

    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                    parsed = datetime.strptime(text, "%Y-%m-%d")
                else:
                    parsed_ts = pd.to_datetime(text, errors="coerce")
                    if not pd.isna(parsed_ts):
                        parsed = parsed_ts.to_pydatetime()
            except Exception:
                parsed = None

    if parsed is None:
        return text if text else t(lang, "na")

    return f"{parsed.day}.{parsed.month}.{parsed.year}"


def mask_account_address(value: str | None, visible_prefix: int = 6, visible_suffix: int = 4) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= visible_prefix + visible_suffix:
        return text
    return f"{text[:visible_prefix]}...{text[-visible_suffix:]}"


def pretty_token(value: str | None, lang: str) -> str:
    text = str(value or "").strip()
    if not text:
        return t(lang, "na")
    if text.lower() == "ok":
        return t(lang, "account_status_ok")
    text = re.sub(r"[_\-]+", " ", text).strip()
    return text.title() if text else t(lang, "na")


def prettify_account_status(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "ok": {"sk": "Snapshot dostupný", "en": "Snapshot available"},
        "connected": {"sk": "Pripojené", "en": "Connected"},
        "available": {"sk": "Dostupné", "en": "Available"},
        "unavailable": {"sk": "Nedostupné", "en": "Unavailable"},
        "error": {"sk": "Nedostupné", "en": "Unavailable"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def prettify_account_action(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "dry_run_execution_bridge": {"sk": "Posledné vyhodnotenie účtu", "en": "Latest account review"},
        "hyperliquid_read_only_snapshot": {"sk": "Obnovenie snapshotu účtu", "en": "Account snapshot refresh"},
        "execution_status_render": {"sk": "Obnovenie prehľadu účtu", "en": "Account summary refresh"},
        "status_refresh": {"sk": "Obnovenie stavu účtu", "en": "Account status refresh"},
        "sync": {"sk": "Synchronizácia účtu", "en": "Account sync"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def prettify_account_result(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "ok": {"sk": "Snapshot bol úspešne obnovený", "en": "Snapshot refreshed successfully"},
        "hold_cash": {"sk": "Bez zmeny, účet zostáva v CASH", "en": "No change, account stays in CASH"},
        "hold_current_position": {"sk": "Systém ponechal aktuálny stav", "en": "System kept the current state"},
        "hold_position": {"sk": "Systém ponechal aktuálnu pozíciu", "en": "System kept the current position"},
        "no_action": {"sk": "Bez zmeny na účte", "en": "No change on the account"},
        "no_new_position": {"sk": "Žiadna nová pozícia", "en": "No new position"},
        "no_position": {"sk": "Žiadna nová pozícia", "en": "No new position"},
        "enter_position": {"sk": "Bola otvorená nová pozícia", "en": "A new position was opened"},
        "open_position": {"sk": "Bola otvorená nová pozícia", "en": "A new position was opened"},
        "rotate_position": {"sk": "Pozícia bola zmenená", "en": "The position was rotated"},
        "exit_to_cash": {"sk": "Pozícia bola uzavretá do CASH", "en": "The position was closed to CASH"},
        "close_position": {"sk": "Pozícia bola uzavretá", "en": "The position was closed"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def describe_bridge_action(value: str | None, lang: str = "sk") -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "refresh": {"sk": "Obnovenie údajov", "en": "Refresh"},
        "dry_run": {"sk": "Kontrola signálu", "en": "Dry-run"},
        "live_execute": {"sk": "Odoslanie obchodu", "en": "Live execute"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def prettify_account_read_mode(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "read_only": {"sk": "Len na citanie", "en": "Read-only"},
        "read_only_operational_view": {"sk": "Prevadzkovy prehlad len na citanie", "en": "Read-only operational view"},
        "operational_read_only_view": {"sk": "Prevadzkovy prehlad len na citanie", "en": "Read-only operational view"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def format_utc_text(value: str | None, lang: str) -> str:
    text = str(value or "").strip()
    if not text:
        return t(lang, "na")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return f"{parsed.day}.{parsed.month}.{parsed.year} {parsed.hour}:{parsed.minute:02d} UTC"
    except ValueError:
        return format_date_text(text, lang)


def format_local_time_text(value: str | None, lang: str) -> str:
    text = str(value or "").strip()
    if not text:
        return t(lang, "na")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return format_date_text(text, lang)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(APP_DISPLAY_TIMEZONE)
        tz_label = parsed.tzname() or "Europe/Bratislava"
        return f"{parsed.day}.{parsed.month}.{parsed.year} {parsed.hour:02d}:{parsed.minute:02d} {tz_label}"
    except ValueError:
        return format_date_text(text, lang)


def render_phase_badge(label: str, background: str) -> None:
    st.markdown(
        (
            "<span style=\"display:inline-block;padding:0.16rem 0.55rem;"
            f"border-radius:999px;background:{background};color:white;"
            "font-size:0.72rem;font-weight:700;letter-spacing:0.03em;\">"
            f"{label}</span>"
        ),
        unsafe_allow_html=True,
    )


def first_float_from_dict(payload: dict | None, keys: list[str]) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if key not in payload:
            continue
        parsed = as_float(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def maybe_pct_from_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return value * 100.0
    return value


def extract_open_position_from_snapshot(snapshot_payload: dict) -> dict | None:
    raw = snapshot_payload.get("raw", {}) if isinstance(snapshot_payload, dict) else {}
    clearinghouse = raw.get("clearinghouseState", {}) if isinstance(raw, dict) else {}
    asset_positions = clearinghouse.get("assetPositions", []) if isinstance(clearinghouse, dict) else []
    if not isinstance(asset_positions, list):
        return None

    for item in asset_positions:
        if not isinstance(item, dict):
            continue
        position = item.get("position") or item.get("pos") or item
        if not isinstance(position, dict):
            continue

        size = first_float_from_dict(position, ["szi", "size", "positionSize"])
        if size is None or abs(size) <= 0:
            continue

        symbol = str(
            position.get("coin")
            or position.get("asset")
            or item.get("coin")
            or item.get("asset")
            or "UNKNOWN"
        ).strip().upper()
        position_value = first_float_from_dict(position, ["positionValue", "position_value"])
        mark_price = first_float_from_dict(position, ["markPx", "mark_price"])
        if mark_price is None and position_value is not None and abs(size) > 0:
            mark_price = abs(position_value / size)

        return {
            "symbol": symbol or "UNKNOWN",
            "side": "LONG" if size > 0 else "SHORT",
            "size": abs(size),
            "entry_price": first_float_from_dict(position, ["entryPx", "entry_price"]),
            "mark_price": mark_price,
            "unrealized_pnl_usd": first_float_from_dict(position, ["unrealizedPnl", "unrealized_pnl", "upl"]),
            "unrealized_pnl_pct": maybe_pct_from_fraction(
                first_float_from_dict(position, ["returnOnEquity", "unrealizedPnlPct", "roe"])
            ),
        }

    return None


def set_default_value(payload: dict, key: str, value) -> None:
    if payload.get(key) is None or payload.get(key) == "":
        payload[key] = value


def build_account_snapshot_view(status_payload: dict, snapshot_payload: dict) -> dict:
    account = dict(status_payload or {})
    snapshot_summary = snapshot_payload.get("summary", {}) if isinstance(snapshot_payload, dict) else {}
    snapshot_source = snapshot_payload.get("source", {}) if isinstance(snapshot_payload, dict) else {}

    set_default_value(account, "provider", snapshot_source.get("provider"))
    set_default_value(account, "account_address", snapshot_payload.get("account_address"))
    set_default_value(account, "as_of_utc", snapshot_payload.get("as_of_utc"))
    set_default_value(account, "status", "ok" if snapshot_payload else None)
    set_default_value(account, "mode", snapshot_payload.get("execution_mode"))
    set_default_value(account, "account_equity_usd", snapshot_summary.get("account_equity_usd"))
    set_default_value(account, "available_balance_usd", snapshot_summary.get("available_balance_usd"))
    set_default_value(account, "balance_source_of_truth", snapshot_summary.get("balance_source_of_truth"))
    set_default_value(account, "positions_count", snapshot_summary.get("positions_count"))
    set_default_value(account, "open_orders_count", snapshot_summary.get("open_orders_count"))
    set_default_value(account, "recent_fills_count", snapshot_summary.get("recent_fills_count"))

    if not isinstance(account.get("open_position"), dict):
        account["open_position"] = extract_open_position_from_snapshot(snapshot_payload)

    if not account.get("current_position"):
        account["current_position"] = (
            account["open_position"]["symbol"]
            if isinstance(account.get("open_position"), dict)
            else "CASH"
        )

    return account


def build_live_execute_gate_state(
    *,
    bridge_available: bool,
    bridge_import_error: str,
    execution_mode_payload: dict,
    live_order_policy_payload: dict,
    dry_run_decision_payload: dict,
    real_order_gate_payload: dict,
) -> dict[str, object]:
    reasons: list[str] = []
    checks = get_nested_dict(real_order_gate_payload, "checks")

    if not bridge_available:
        reasons.append("APP bridge pre live execute nie je dostupny.")
        if bridge_import_error:
            reasons.append(f"Import bridge zlyhal: {bridge_import_error}")
    if not execution_mode_payload:
        reasons.append("Chyba execution_mode.json.")
    if not live_order_policy_payload:
        reasons.append("Chyba live_order_policy.json.")
    if not dry_run_decision_payload:
        reasons.append("Chyba latest_dry_run_decision.json.")
    if not real_order_gate_payload:
        reasons.append("Chyba latest_real_order_gate_decision.json.")

    if execution_mode_payload and str(execution_mode_payload.get("mode") or "").strip().lower() != "live":
        reasons.append("execution_mode.json nema mode=live.")
    if execution_mode_payload and as_bool(execution_mode_payload.get("trading_enabled")) is not True:
        reasons.append("execution_mode.json nema trading_enabled=true.")
    if live_order_policy_payload and as_bool(live_order_policy_payload.get("allow_live_orders")) is not True:
        reasons.append("live_order_policy.json nema allow_live_orders=true.")
    if live_order_policy_payload and as_bool(live_order_policy_payload.get("manual_approval_required")) is True:
        reasons.append("live_order_policy.json stale vyzaduje manual_approval_required=true.")
    if (
        execution_mode_payload
        and live_order_policy_payload
        and as_bool(live_order_policy_payload.get("require_kill_switch_off")) is True
        and as_bool(execution_mode_payload.get("kill_switch")) is True
    ):
        reasons.append("Live policy vyzaduje kill_switch=false.")

    gate_status = str(real_order_gate_payload.get("status") or "").strip()
    if real_order_gate_payload and gate_status != "ready_if_enabled":
        reasons.append(f"Gate status nie je ready_if_enabled: {gate_status or 'neznamy'}.")
    if real_order_gate_payload and as_bool(real_order_gate_payload.get("would_place_real_order")) is not True:
        reasons.append("Gate artefakt nepotvrdzuje would_place_real_order=true.")
    if real_order_gate_payload and checks and as_bool(checks.get("approval_status_allowed")) is not True:
        reasons.append("Approval status nie je povoleny pre live execute.")
    if real_order_gate_payload and checks and as_bool(checks.get("leverage_live_truth_allowed")) is not True:
        reasons.append("Gate nepotvrdzuje leverage_live_truth_allowed=true.")
    if real_order_gate_payload and checks and as_bool(checks.get("account_address_present")) is not True:
        reasons.append("Gate nepotvrdzuje account_address.")

    dry_run_action = str(dry_run_decision_payload.get("recommended_action") or "").strip()
    dry_run_would_place_order = as_bool(
        get_nested_value(dry_run_decision_payload, "simulated_order", "would_place_order")
    )
    if dry_run_decision_payload and dry_run_would_place_order is not True:
        reasons.append(
            "Dry-run dnes neukazuje realny submit "
            f"({dry_run_action or 'neznamy stav'})."
        )
    if dry_run_decision_payload and dry_run_action.startswith("block_"):
        reasons.append(f"Dry-run hlasi blocker: {dry_run_action}.")
    if dry_run_decision_payload and as_bool(dry_run_decision_payload.get("stale_signal")) is True:
        reasons.append("Dry-run hlasi stale_signal=true.")
    if dry_run_decision_payload and as_bool(dry_run_decision_payload.get("duplicate_order_risk")) is True:
        reasons.append("Dry-run hlasi duplicate_order_risk=true.")
    if (
        dry_run_decision_payload
        and as_bool(get_nested_value(dry_run_decision_payload, "guardrails", "contract_validated")) is not True
    ):
        reasons.append("Dry-run nema guardrails.contract_validated=true.")

    for item in real_order_gate_payload.get("block_reasons", []) or []:
        text = str(item).strip()
        if text and text not in reasons:
            reasons.append(text)

    return {
        "ok": not reasons,
        "reasons": reasons,
        "status": gate_status,
        "would_place_real_order": as_bool(real_order_gate_payload.get("would_place_real_order")),
    }


def prettify_trading_operation_mode(value: str | None, lang: str) -> str:
    mode = str(value or "").strip().lower()
    mapping = {
        "manual": {
            "sk": "Manualne obchody",
            "en": "Manual trading",
        },
        "automatic": {
            "sk": "Automaticke obchody",
            "en": "Automatic trading",
        },
    }
    if mode in mapping:
        return mapping[mode][lang]
    return pretty_token(value, lang)


def build_strategy_state_label(operation_mode: str | None, lang: str) -> str:
    mode = str(operation_mode or "").strip().lower()
    if not mode:
        return "Stratégia vypnutá" if lang == "sk" else "Strategy off"
    if mode == "automatic":
        return "Stratégia zapnutá" if lang == "sk" else "Strategy on"
    return "Stratégia vypnutá" if lang == "sk" else "Strategy off"


def build_safety_posture_label(payload: dict[str, Any], lang: str) -> str:
    if not payload:
        return "Chyba execution_mode.json." if lang == "sk" else "execution_mode.json missing."
    mode = str(payload.get("mode") or "").strip().lower()
    trading_enabled = as_bool(payload.get("trading_enabled"))
    kill_switch = as_bool(payload.get("kill_switch"))
    if mode == "live" and trading_enabled is True and kill_switch is False:
        return "Live povolene" if lang == "sk" else "Live armed"
    if mode == "read_only" and trading_enabled is False and kill_switch is True:
        return "Fail-closed"
    return pretty_token(mode or "unknown", lang)


def build_safety_posture_detail(payload: dict[str, Any], lang: str) -> str:
    if not payload:
        return (
            "execution_mode.json chyba alebo je neplatny."
            if lang == "sk"
            else "execution_mode.json missing or invalid."
        )
    mode = str(payload.get("mode") or "").strip() or "unknown"
    trading_enabled = payload.get("trading_enabled")
    kill_switch = payload.get("kill_switch")
    return (
        f"mode={mode} | trading_enabled={trading_enabled} | kill_switch={kill_switch}"
    )


def extract_trading_operation_mode_bridge_payload(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    bridge_payload = result.get("trading_operation_mode")
    if isinstance(bridge_payload, dict):
        payload = dict(bridge_payload)
    else:
        summary = result.get("result_summary")
        nested_payload = summary.get("trading_operation_mode") if isinstance(summary, dict) else None
        payload = dict(nested_payload) if isinstance(nested_payload, dict) else {}
    if not payload:
        return {}
    payload["mode"] = str(payload.get("mode") or "").strip().lower()
    payload["source_path"] = str(
        payload.get("source_path")
        or TRADING_OPERATION_MODE_CONFIG_PATH.resolve()
    )
    return payload


def load_trading_operation_mode_via_bridge() -> tuple[dict[str, Any], dict[str, Any]]:
    if not callable(run_app_execute_action):
        result = {
            "action": "get_mode",
            "ok": False,
            "status": "blocked",
            "error": APP_EXECUTE_BRIDGE_IMPORT_ERROR or "APP bridge unavailable.",
            "user_summary": APP_EXECUTE_BRIDGE_IMPORT_ERROR or "APP bridge unavailable.",
        }
        payload = {
            "mode": "",
            "updated_at_utc": None,
            "updated_by": "bridge_unavailable",
            "fail_closed": True,
            "error": result["error"],
            "source_path": str(TRADING_OPERATION_MODE_CONFIG_PATH.resolve()),
        }
        return result, payload

    result = run_app_execute_action(action="get_mode")
    payload = extract_trading_operation_mode_bridge_payload(result)
    if payload:
        return result, payload

    return result, {
        "mode": "",
        "updated_at_utc": None,
        "updated_by": "bridge_unknown",
        "fail_closed": True,
        "error": str(result.get("error") or "APP bridge returned no trading mode payload.").strip(),
        "source_path": str(TRADING_OPERATION_MODE_CONFIG_PATH.resolve()),
    }


def build_signal_result_label(payload: dict[str, Any], lang: str) -> str:
    if not payload:
        return "Signal nedostupny" if lang == "sk" else "Signal unavailable"
    recommended_action = str(payload.get("recommended_action") or "").strip().lower()
    target_asset = str(payload.get("target_asset") or "").strip().upper() or "N/A"
    would_place_order = as_bool(
        get_nested_value(payload, "simulated_order", "would_place_order")
    )
    if as_bool(payload.get("stale_signal")) is True:
        return "Stale signal"
    if would_place_order is True and target_asset and target_asset != "CASH":
        return (
            f"Trade na {target_asset}" if lang == "sk" else f"Trade to {target_asset}"
        )
    if recommended_action == "hold_cash":
        return "Dnes bez obchodu" if lang == "sk" else "No trade today"
    return pretty_token(recommended_action or "unknown", lang)


def build_signal_result_detail(payload: dict[str, Any], lang: str) -> str:
    if not payload:
        return (
            "latest_dry_run_decision.json chyba."
            if lang == "sk"
            else "latest_dry_run_decision.json missing."
        )
    recommended_action = str(payload.get("recommended_action") or "").strip() or "unknown"
    target_asset = str(payload.get("target_asset") or "").strip().upper() or "N/A"
    would_place_order = as_bool(
        get_nested_value(payload, "simulated_order", "would_place_order")
    )
    return (
        f"recommended_action={recommended_action} | target_asset={target_asset} | "
        f"would_place_order={would_place_order}"
    )


def build_gate_result_label(payload: dict[str, Any], lang: str) -> str:
    if not payload:
        return "Gate nedostupny" if lang == "sk" else "Gate unavailable"
    status = str(payload.get("status") or "").strip().lower()
    if status == "ready_if_enabled":
        return "Gate pripraveny" if lang == "sk" else "Gate ready"
    if payload.get("block_reasons"):
        return "Gate blokuje" if lang == "sk" else "Gate blocked"
    return pretty_token(status or "unknown", lang)


def build_gate_result_detail(payload: dict[str, Any], lang: str) -> str:
    if not payload:
        return (
            "latest_real_order_gate_decision.json chyba."
            if lang == "sk"
            else "latest_real_order_gate_decision.json missing."
        )
    status = str(payload.get("status") or "").strip() or "unknown"
    would_place_real_order = as_bool(payload.get("would_place_real_order"))
    return f"status={status} | would_place_real_order={would_place_real_order}"


def build_scheduler_mode_explanation(mode: str, lang: str) -> str:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode == "automatic":
        return (
            "Scheduler vyhodnocuje signal a odosle obchod iba vtedy, ked existuje validny trade a prejdu vsetky gate checks."
            if lang == "sk"
            else "The scheduler evaluates the signal and auto-sends only when a valid trade exists and all gate checks pass."
        )
    return (
        "Scheduler iba vyhodnocuje refresh, signal, reconciliation a gate. Automaticke odoslanie je vypnute."
        if lang == "sk"
        else "The scheduler only evaluates refresh, signal, reconciliation, and gate. Auto-send is disabled."
    )


def friendly_hyperliquid_error_message(error_text: str, lang: str) -> str | None:
    text = str(error_text or "").strip()
    if not text:
        return None

    lowered = text.lower()
    hyperliquid_error = (
        "hyperliquid" in lowered
        or "api.hyperliquid.xyz" in lowered
        or "nameresolutionerror" in lowered
        or "failed to resolve" in lowered
    )
    if not hyperliquid_error:
        return None

    if lang != "sk":
        return "Could not connect to the Hyperliquid API."

    reason = ""
    if "nameresolutionerror" in lowered or "failed to resolve" in lowered:
        reason = "Dovod: NameResolutionError - nepodarilo sa prelozit adresu api.hyperliquid.xyz."
    elif "connection refused" in lowered:
        reason = "Dovod: API spojenie bolo odmietnute."
    elif "timeout" in lowered:
        reason = "Dovod: API neodpovedalo vcas."

    if reason:
        return "Nepodarilo sa spojiť s Hyperliquid API.\n" + reason
    return "Nepodarilo sa spojiť s Hyperliquid API."


def friendly_execution_error_message(error_text: str, lang: str) -> str | None:
    text = str(error_text or "").strip()
    if not text:
        return None

    lowered = text.lower()
    if (
        "build_execution_intent_from_strategy_exports" in lowered
        and ("missing required csv" in lowered or "missing required file" in lowered)
    ):
        if lang == "sk":
            return "Kontrolu signalu sa teraz nepodarilo dokoncit. Chybaju aktualne podklady strategie."
        return "Signal check could not finish because current strategy inputs are missing."
    return None


def simplify_live_block_reason(reason: str, lang: str) -> str:
    text = str(reason or "").strip()
    if not text or lang != "sk":
        return text

    lowered = text.lower()

    if "leverage_live_truth_allowed=true" in text:
        return "Dnešný signál ešte nespĺňa všetky podmienky."
    if "dry-run dnes neukazuje realny submit" in lowered and "hold_cash" in lowered:
        return "Dnes nie je vhodný signál."
    if "dry-run dnes neukazuje realny submit" in lowered:
        return "Dnes nie je vhodný signál."
    if "dry-run hlasi blocker" in lowered:
        return "Dnešný signál je blokovaný."
    if "stale_signal=true" in lowered:
        return "Dnešný signál je zastaraný."
    if "duplicate_order_risk=true" in lowered:
        return "Systém teraz nechce poslať duplicitný obchod."
    if "contract_validated=true" in lowered:
        return "Bezpečnostná kontrola dnes nie je potvrdená."
    if "execution_mode.json nema mode=live" in lowered:
        return "Odoslanie obchodu teraz nie je zapnuté."
    if "execution_mode.json nema trading_enabled=true" in lowered:
        return "Odoslanie obchodu je teraz vypnuté."
    if "allow_live_orders=true" in lowered:
        return "Odoslanie obchodu teraz nie je povolené."
    if "manual_approval_required=true" in lowered:
        return "Obchod ešte vyžaduje manuálne schválenie."
    if "kill_switch=false" in lowered:
        return "Bezpečnostná poistka je zapnutá."
    if "gate status nie je ready_if_enabled" in lowered:
        return "Systém dnes ešte nepovolil odoslanie obchodu."
    if "approval status nie je povoleny" in lowered:
        return "Schválenie pre odoslanie obchodu ešte nie je hotové."
    if "account_address" in lowered:
        return "Chýba pripojený účet."
    if "bridge pre live execute nie je dostupny" in lowered:
        return "Táto akcia teraz nie je dostupná."

    return text


def build_live_blocked_notice(block_reasons: list[str], lang: str) -> str:
    reasons = [str(item or "").strip() for item in block_reasons if str(item or "").strip()]
    if lang == "sk":
        if "Dnes nie je vhodný signál." in reasons:
            return "Dnes sa obchod neodošle, pretože systém momentálne nevidí vhodný obchod."
        first_reason = reasons[0] if reasons else ""
        if first_reason:
            return f"Obchod sa teraz neodošle. {first_reason}"
        return "Obchod sa teraz neodošle."
    first_reason = reasons[0] if reasons else ""
    return first_reason or "Order will not be sent."


def build_execution_notice(result: dict[str, Any], lang: str) -> str:
    if not result:
        return ""

    def normalize_execution_asset(value: Any) -> str:
        return str(value or "").strip().upper()

    action = str(result.get("action") or "").strip().lower()
    status = str(result.get("status") or "").strip().lower()
    error_text = str(result.get("error") or "").strip()
    user_summary = str(result.get("user_summary") or "").strip()
    result_summary = result.get("result_summary") if isinstance(result.get("result_summary"), dict) else {}
    recommended_action = str(result_summary.get("recommended_action") or "").strip().lower()
    current_position = normalize_execution_asset(result_summary.get("current_position"))
    target_asset = normalize_execution_asset(result_summary.get("target_asset"))
    order_step_present = bool(result_summary.get("order_step_present"))
    mode = str(result_summary.get("mode") or "").strip().lower()
    first_block_reason = ""

    if lang == "sk":
        friendly_error = friendly_hyperliquid_error_message(error_text, lang)
        if friendly_error:
            return friendly_error
        friendly_error = friendly_execution_error_message(error_text, lang)
        if friendly_error:
            return friendly_error

        block_reasons = [
            simplify_live_block_reason(item, lang)
            for item in (result.get("block_reasons") or [])
        ]
        block_reasons = [item for item in block_reasons if item]
        if block_reasons:
            first_block_reason = block_reasons[0]

        if action == "refresh" and result.get("ok"):
            if current_position and current_position != "CASH":
                return (
                    "Údaje o účte sa úspešne obnovili. "
                    f"Účet je aktuálny a momentálne drží {current_position}."
                )
            return "Údaje o účte sa úspešne obnovili. Účet je aktuálny a momentálne nemá otvorenú pozíciu."

        if action == "dry_run" and recommended_action == "hold_cash":
            return "Kontrola signálu je hotová. Dnes systém nevidí vhodný obchod."

        if action == "dry_run" and result.get("ok"):
            if target_asset and target_asset != "CASH":
                return (
                    "Kontrola signálu je hotová. "
                    f"Dnes systém vidí obchod smerom na {target_asset}."
                )
            return "Kontrola signálu je hotová."

        if action == "get_mode" and result.get("ok"):
            return (
                "Aktualny rezim obchodovania je automaticky."
                if mode == "automatic"
                else "Aktualny rezim obchodovania je manualny."
            )

        if action in {"set_manual_mode", "set_automatic_mode"} and result.get("ok"):
            return (
                "Automatické obchody sú zapnuté."
                if mode == "automatic"
                else "Automatické obchody sú vypnuté."
            )

        if action == "live_execute" and status == "blocked":
            return build_live_blocked_notice(block_reasons, lang)

        if action == "live_execute" and result.get("ok"):
            if order_step_present:
                return "Obchod bol odoslaný."
            return "Pokyn sa spracoval, ale obchod sa neodoslal."

        if user_summary:
            return user_summary
        if error_text:
            return error_text
        return "Akcia sa skončila bez detailu."

    return user_summary or error_text or "Action finished."


def prettify_balance_source(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return t(lang, "na")
    if text == "spot_stable_balance":
        return "Spot stable balance"
    if text == "perp_clearinghouse":
        return "Perp clearinghouse"
    return pretty_token(text, lang)


def prettify_account_status(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "ok": {"sk": "Udaje su dostupne", "en": "Snapshot available"},
        "connected": {"sk": "Pripojene", "en": "Connected"},
        "available": {"sk": "Dostupne", "en": "Available"},
        "unavailable": {"sk": "Nedostupne", "en": "Unavailable"},
        "error": {"sk": "Nedostupne", "en": "Unavailable"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def prettify_account_action(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "dry_run_execution_bridge": {"sk": "Kontrola uctu", "en": "Latest account review"},
        "hyperliquid_read_only_snapshot": {"sk": "Obnovenie udajov", "en": "Account snapshot refresh"},
        "execution_status_render": {"sk": "Obnovenie prehladu", "en": "Account summary refresh"},
        "status_refresh": {"sk": "Obnovenie stavu", "en": "Account status refresh"},
        "sync": {"sk": "Synchronizacia uctu", "en": "Account sync"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


def prettify_account_result(value: str | None, lang: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "ok": {"sk": "Udaje boli uspesne obnovene", "en": "Snapshot refreshed successfully"},
        "hold_cash": {"sk": "Bez zmeny, ucet zostava v hotovosti", "en": "No change, account stays in CASH"},
        "hold_current_position": {"sk": "Aktualny stav zostal bez zmeny", "en": "System kept the current state"},
        "hold_position": {"sk": "Aktualna pozicia zostala bez zmeny", "en": "System kept the current position"},
        "no_action": {"sk": "Bez zmeny na ucte", "en": "No change on the account"},
        "no_new_position": {"sk": "Ziadna nova pozicia", "en": "No new position"},
        "no_position": {"sk": "Ziadna nova pozicia", "en": "No new position"},
        "enter_position": {"sk": "Bola otvorena nova pozicia", "en": "A new position was opened"},
        "open_position": {"sk": "Bola otvorena nova pozicia", "en": "A new position was opened"},
        "rotate_position": {"sk": "Pozicia sa zmenila", "en": "The position was rotated"},
        "exit_to_cash": {"sk": "Pozicia bola uzavreta a ucet je v hotovosti", "en": "The position was closed to CASH"},
        "close_position": {"sk": "Pozicia bola uzavreta", "en": "The position was closed"},
    }
    if text in mapping:
        return mapping[text][lang]
    return pretty_token(value, lang)


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


def prettify_asset_public(value: Any, lang: str) -> str:
    if value is None:
        return t(lang, "na")
    numeric = as_float(value)
    if numeric is not None:
        if math.isclose(numeric, 0.0, abs_tol=1e-12):
            return t(lang, "cash")
        return t(lang, "na")
    raw = str(value).strip().upper()
    if raw in {"", "NONE"}:
        return t(lang, "na")
    if raw in {
        "CASH",
        "0",
        "0.0",
        "0.00",
        "ZERO",
        "ZERO EXPOSURE",
        "ZERO_EXPOSURE",
        "BASE",
        "BASELINE",
        "CORE",
        "BASELINE_RISK",
        "EARLY_RISK",
        "FULL_RISK",
    }:
        return t(lang, "cash")
    return raw


def resolve_homepage_held_state(live_public_state: dict[str, Any], lang: str) -> str:
    held_asset_public = live_public_state.get("held_asset_public")
    execution_state = str(live_public_state.get("execution_state") or "").strip().upper()
    portfolio_held_asset = str(live_public_state.get("portfolio_held_asset") or "").strip().upper()
    baseline_held_asset = str(live_public_state.get("baseline_held_asset") or "").strip().upper()
    tradable_governed_asset = str(live_public_state.get("tradable_governed_asset") or "").strip().upper()
    cash_day = as_bool(live_public_state.get("cash_day"))

    cash_like_tokens = {
        "",
        "0",
        "0.0",
        "0.00",
        "CASH",
        "BASE",
        "BASELINE",
        "CORE",
        "BASELINE_RISK",
        "EARLY_RISK",
        "FULL_RISK",
        "NONE",
        "NULL",
    }

    for candidate in [held_asset_public, execution_state, portfolio_held_asset, tradable_governed_asset, baseline_held_asset]:
        if candidate is None:
            continue
        text_value = str(candidate).strip().upper()
        if text_value in cash_like_tokens:
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9_\-]*", text_value):
            return text_value

    if cash_day is True:
        return "CASH"

    raw = str(held_asset_public or "").strip().upper()
    if raw in cash_like_tokens or raw == "":
        return "CASH"

    return "CASH"


def trend_cross_text(trend_live: dict, lang: str) -> str:
    if trend_live.get("crossed_up_today") is True:
        return "Cross up on calc date" if lang == "en" else "Prechod hore k dátumu výpočtu"
    if trend_live.get("crossed_down_today") is True:
        return "Cross down on calc date" if lang == "en" else "Prechod dole k dátumu výpočtu"
    return t(lang, "trend_cross_none")


def prettify_live_mode(value: str | None, lang: str) -> str:
    if value is None:
        return t(lang, "na")
    raw = str(value).strip().lower()
    mapping = {
        "1.0x_without_leverage": {"sk": "Bez leverage", "en": "Without leverage"},
        "phase68g_etf_flow_impulse_early_risk_cooldown_15": {"sk": "Hlavna strategia", "en": "Main strategy"},
        "phase68g_btc_persistence_10d_early_risk_075": {"sk": "Maksi fallback", "en": "Softer fallback"},
        "phase68g_66g_1p25x_candidate": {"sk": "Sekundarny fallback", "en": "Secondary fallback"},
        "phase68i_dynamic_ladder_candidate": {"sk": "Historicky fallback", "en": "Historical fallback"},
    }
    return mapping.get(raw, {"sk": str(value), "en": str(value)})[lang]


def prettify_execution_profile(value: str | None, lang: str) -> str:
    if value is None:
        return t(lang, "na")
    raw = str(value).strip().lower()
    mapping = {
        "unlevered": {"sk": "Bez leverage", "en": "Without leverage"},
        "none": {"sk": "Bez leverage", "en": "Without leverage"},
        "dynamic_ladder": {"sk": "Historicky fallback", "en": "Historical fallback"},
        "static_1p25x": {"sk": "Sekundarny fallback", "en": "Secondary fallback"},
        "phase68g_etf_flow_impulse_early_risk_cooldown_15": {"sk": "Hlavna strategia", "en": "Main strategy"},
        "phase68g_btc_persistence_10d_early_risk_075": {"sk": "Maksi fallback", "en": "Softer fallback"},
        "phase68g_66g_1p25x_candidate": {"sk": "Sekundarny fallback", "en": "Secondary fallback"},
        "phase68i_dynamic_ladder_candidate": {"sk": "Historicky fallback", "en": "Historical fallback"},
    }
    return mapping.get(raw, {"sk": str(value), "en": str(value)})[lang]


def valid_email(value: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value.strip()))


# =========================================================
# STYLING
# =========================================================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2.4rem;
            max-width: 1380px;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(17,138,178,0.12), transparent 24%),
                radial-gradient(circle at top right, rgba(165,110,255,0.12), transparent 24%),
                radial-gradient(circle at bottom center, rgba(6,214,160,0.06), transparent 28%),
                linear-gradient(180deg, #0a0f18 0%, #0d1320 50%, #0a0f18 100%);
        }

        .hero-wrap {
            background:
                radial-gradient(circle at top left, rgba(17,138,178,0.22), transparent 34%),
                radial-gradient(circle at top right, rgba(165,110,255,0.20), transparent 34%),
                linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.016));
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 28px;
            padding: 1.4rem 1.4rem 1.15rem 1.4rem;
            margin-bottom: 1.15rem;
            box-shadow:
                0 18px 56px rgba(0,0,0,0.34),
                inset 0 1px 0 rgba(255,255,255,0.04);
            position: relative;
            overflow: hidden;
        }

        .hero-wrap::after {
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.03) 45%, transparent 90%);
            pointer-events: none;
        }

        .gradient-line {
            height: 4px;
            width: 100%;
            background: linear-gradient(90deg, #ff6b6b, #ffd166, #06d6a0, #118ab2, #a56eff);
            border-radius: 999px;
            margin: 0.45rem 0 1.15rem 0;
            box-shadow: 0 0 22px rgba(165,110,255,0.26);
        }

        .lang-wrap {
            margin-top: 0.7rem;
            margin-bottom: 1rem;
        }

        .btc-side-indicator {
            border-radius: 18px;
            padding: 0.95rem 1rem 0.95rem 1rem;
            min-height: 108px;
            border: 1px solid rgba(255,255,255,0.10);
            background:
                radial-gradient(circle at top right, rgba(255,196,61,0.16), transparent 38%),
                linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.020));
            box-shadow:
                0 12px 30px rgba(0,0,0,0.20),
                inset 0 1px 0 rgba(255,255,255,0.04);
            display: grid;
            gap: 0.7rem;
        }

        .btc-side-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .btc-side-label {
            font-size: 0.72rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: rgba(226,232,240,0.62);
        }

        .btc-side-arrow {
            font-size: 1.5rem;
            line-height: 1;
        }

        .btc-side-body {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .btc-side-main {
            display: flex;
            align-items: center;
            gap: 0.48rem;
            font-size: 1.36rem;
            font-weight: 700;
            line-height: 1.1;
            color: #f8fafc;
        }

        .btc-side-main.is-up {
            color: #8ee6b3;
        }

        .btc-side-main.is-down {
            color: #ff9d9d;
        }

        .btc-side-main.is-flat {
            color: rgba(226,232,240,0.72);
        }

        .btc-side-price {
            font-size: 1.18rem;
            font-weight: 720;
            color: #f8fafc;
            text-align: right;
        }

        div[data-testid="stRadio"] > div {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 999px;
            padding: 5px 10px;
            width: fit-content;
            box-shadow: 0 8px 22px rgba(0,0,0,0.16);
        }

        .card {
            border-radius: 20px;
            padding: 16px 18px;
            min-height: 118px;
            border: 1px solid rgba(255,255,255,0.10);
            box-shadow:
                0 12px 34px rgba(0,0,0,0.22),
                inset 0 1px 0 rgba(255,255,255,0.03);
            margin-bottom: 12px;
            backdrop-filter: blur(6px);
        }

        .card-blue {
            background: linear-gradient(180deg, rgba(64,140,255,0.18), rgba(255,255,255,0.025));
        }

        .card-green {
            background: linear-gradient(180deg, rgba(6,214,160,0.18), rgba(255,255,255,0.025));
        }

        .card-violet {
            background: linear-gradient(180deg, rgba(165,110,255,0.18), rgba(255,255,255,0.025));
        }

        .card-orange {
            background: linear-gradient(180deg, rgba(255,161,90,0.18), rgba(255,255,255,0.025));
        }

        .card-neutral {
            background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.022));
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
            letter-spacing: 0.01em;
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
            line-height: 1.1;
            margin-bottom: 7px;
            text-shadow: 0 0 18px rgba(255,255,255,0.05);
        }

        .card-sub {
            font-size: 0.92rem;
            opacity: 0.84;
        }

        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.018));
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 20px;
            padding: 16px 18px;
            min-height: 118px;
            margin-bottom: 12px;
            box-shadow:
                0 12px 34px rgba(0,0,0,0.22),
                inset 0 1px 0 rgba(255,255,255,0.03);
        }

        div[data-testid="stDataFrame"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.018));
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.09);
            margin-bottom: 12px;
            box-shadow:
                0 12px 34px rgba(0,0,0,0.22),
                inset 0 1px 0 rgba(255,255,255,0.03);
        }

        .app-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            overflow: hidden;
            border-radius: 18px;
            border: 1px solid rgba(255,255,255,0.09);
            background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.016));
            box-shadow: 0 10px 28px rgba(0,0,0,0.16);
            margin: 0.35rem 0 0.85rem 0;
            font-family: inherit;
        }

        .app-table th,
        .app-table td {
            padding: 0.78rem 0.92rem;
            border-bottom: 1px solid rgba(255,255,255,0.07);
            border-right: 1px solid rgba(255,255,255,0.05);
            text-align: left;
            font-family: inherit;
        }

        .app-table th {
            background: rgba(255,255,255,0.045);
            color: rgba(226,232,240,0.68);
            font-size: 0.82rem;
            font-weight: 650;
        }

        .app-table td {
            color: #f8fafc;
            font-size: 0.95rem;
            font-weight: 620;
        }

        .app-table tr:last-child td {
            border-bottom: 0;
        }

        .app-table th:last-child,
        .app-table td:last-child {
            border-right: 0;
        }

        .ops-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
            padding: 12px 14px;
            border-radius: 18px;
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow:
                0 10px 28px rgba(0,0,0,0.18),
                inset 0 1px 0 rgba(255,255,255,0.03);
            margin-bottom: 10px;
        }

        .ops-strip-item {
            min-width: 0;
        }

        .ops-strip-label {
            font-size: 0.68rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: rgba(226,232,240,0.62);
            margin-bottom: 3px;
        }

        .ops-strip-value {
            font-size: 0.98rem;
            line-height: 1.2;
            font-weight: 650;
            color: #f8fafc;
        }

        .ops-strip-sub {
            font-size: 0.78rem;
            color: rgba(226,232,240,0.72);
            margin-top: 3px;
        }

        .ops-kpi-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 10px;
            margin-bottom: 10px;
        }

        .ops-kpi {
            border-radius: 18px;
            padding: 13px 14px;
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow:
                0 10px 24px rgba(0,0,0,0.18),
                inset 0 1px 0 rgba(255,255,255,0.03);
        }

        .ops-kpi-label {
            font-size: 0.72rem;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            color: rgba(226,232,240,0.62);
            margin-bottom: 6px;
        }

        .ops-kpi-value {
            font-size: 1.42rem;
            font-weight: 720;
            line-height: 1.08;
            color: #ffffff;
            margin-bottom: 4px;
        }

        .ops-kpi-sub {
            font-size: 0.8rem;
            color: rgba(226,232,240,0.72);
        }

        .ops-panel {
            border-radius: 18px;
            padding: 12px 14px;
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow:
                0 10px 24px rgba(0,0,0,0.18),
                inset 0 1px 0 rgba(255,255,255,0.03);
            margin-bottom: 10px;
        }

        .ops-panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 10px;
        }

        .ops-panel-title {
            font-size: 0.98rem;
            font-weight: 650;
            color: #f8fafc;
        }

        .ops-inline-note {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 8px;
            margin: 2px 0 10px 0;
            color: rgba(226,232,240,0.8);
            font-size: 0.86rem;
        }

        .ops-inline-note-label {
            color: rgba(226,232,240,0.56);
        }

        .ops-inline-note-value {
            color: #f8fafc;
            font-weight: 600;
        }

        .ops-chip-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
            gap: 8px;
        }

        .ops-chip {
            border-radius: 14px;
            padding: 9px 10px;
            background: rgba(255,255,255,0.035);
            border: 1px solid rgba(255,255,255,0.06);
        }

        .ops-chip-label {
            font-size: 0.67rem;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: rgba(226,232,240,0.56);
            margin-bottom: 4px;
        }

        .ops-chip-value {
            font-size: 0.94rem;
            line-height: 1.2;
            font-weight: 620;
            color: #f8fafc;
        }

        .ops-chip-sub {
            font-size: 0.77rem;
            color: rgba(226,232,240,0.68);
            margin-top: 4px;
        }

        .ops-detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 8px;
        }

        .ops-detail-item {
            border-radius: 14px;
            padding: 10px 11px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
        }

        .ops-detail-label {
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: rgba(226,232,240,0.56);
            margin-bottom: 5px;
        }

        .ops-detail-value {
            font-size: 0.95rem;
            line-height: 1.25;
            font-weight: 620;
            color: #f8fafc;
        }

        .ops-tone-proof {
            background: linear-gradient(180deg, rgba(61,94,124,0.34), rgba(255,255,255,0.018));
        }

        .ops-tone-overview {
            background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.016));
        }

        .ops-tone-balance {
            background: linear-gradient(180deg, rgba(20,126,104,0.24), rgba(255,255,255,0.018));
        }

        .ops-tone-position {
            background: linear-gradient(180deg, rgba(49,86,134,0.22), rgba(255,255,255,0.018));
        }

        .ops-tone-activity {
            background: linear-gradient(180deg, rgba(112,90,49,0.20), rgba(255,255,255,0.018));
        }

        .ops-tone-detail {
            background: linear-gradient(180deg, rgba(255,255,255,0.036), rgba(255,255,255,0.012));
        }

        .ops-tone-control {
            background: linear-gradient(180deg, rgba(90,109,136,0.24), rgba(255,255,255,0.018));
        }

        .story-panel {
            border-radius: 20px;
            padding: 1rem 1.05rem;
            border: 1px solid rgba(255,255,255,0.08);
            background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.016));
            box-shadow:
                0 12px 28px rgba(0,0,0,0.22),
                inset 0 1px 0 rgba(255,255,255,0.03);
            min-height: 100%;
        }

        .story-panel.story-warm {
            background: linear-gradient(180deg, rgba(132,94,34,0.22), rgba(255,255,255,0.016));
        }

        .story-panel.story-cool {
            background: linear-gradient(180deg, rgba(52,94,146,0.22), rgba(255,255,255,0.016));
        }

        .story-panel.story-alert {
            background: linear-gradient(180deg, rgba(125,67,54,0.22), rgba(255,255,255,0.016));
        }

        .story-panel.story-proof {
            background: linear-gradient(180deg, rgba(45,116,93,0.22), rgba(255,255,255,0.016));
        }

        .story-eyebrow {
            font-size: 0.72rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: rgba(226,232,240,0.58);
            margin-bottom: 0.45rem;
        }

        .story-title {
            font-size: 1.02rem;
            font-weight: 680;
            line-height: 1.2;
            color: #ffffff;
            margin-bottom: 0.45rem;
        }

        .story-body {
            font-size: 0.93rem;
            line-height: 1.55;
            color: rgba(248,250,252,0.90);
        }

        .story-body + .story-body {
            margin-top: 0.55rem;
        }

        .story-list {
            margin: 0.35rem 0 0 0;
            padding-left: 1rem;
            color: rgba(248,250,252,0.90);
        }

        .story-list li {
            margin: 0.22rem 0;
            line-height: 1.45;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


def render_color_card(label: str, value: str, subtitle: str = "", help_text: str | None = None, accent: str = "neutral") -> None:
    help_html = ""
    if help_text:
        safe_help = escape_html_text(help_text).replace('"', "&quot;")
        help_html = f'<span class="card-info" title="{safe_help}">i</span>'
    safe_label = escape_html_text(label)
    safe_value = escape_html_text(value)
    safe_subtitle = escape_html_text(subtitle)

    st.markdown(
        f"""
        <div class="card card-{accent}">
            <div class="card-top">
                <div class="card-label">{safe_label}</div>
                {help_html}
            </div>
            <div class="card-value">{safe_value}</div>
            <div class="card-sub">{safe_subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_box(label: str, value: str, help_text: str | None = None) -> None:
    st.metric(label=label, value=value, help=help_text, border=True)


def escape_html_text(value) -> str:
    return html.escape(str(value if value is not None else ""))


def render_legacy_csv_btc_side_indicator(indicator: dict[str, Any]) -> None:
    if not indicator:
        return

    label = escape_html_text(indicator.get("label", "BTC"))
    direction = escape_html_text(indicator.get("direction", ""))
    change_text = escape_html_text(indicator.get("change_text", ""))
    price_text = escape_html_text(indicator.get("price_text", ""))
    direction_class = "is-up" if indicator.get("direction") == "↑" else "is-down"
    price_html = f'<div class="btc-side-price">{price_text}</div>' if price_text else ""

    st.markdown(
        (
            '<div class="btc-side-indicator">'
            f'<div class="btc-side-head"><div class="btc-side-label">{label}</div>{price_html}</div>'
            f'<div class="btc-side-body"><div class="btc-side-main {direction_class}"><span class="btc-side-arrow">{direction}</span><span>{change_text}</span></div></div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_btc_side_indicator(indicator: dict[str, Any]) -> None:
    if not indicator:
        return

    label = escape_html_text(indicator.get("label", "BTC"))
    change_text = escape_html_text(indicator.get("change_text", ""))
    price_text = escape_html_text(indicator.get("price_text", ""))
    direction = str(indicator.get("direction") or "flat").strip().lower()
    direction_class = {"up": "is-up", "down": "is-down"}.get(direction, "is-flat")
    direction_symbol = {"up": "&uarr;", "down": "&darr;"}.get(direction, "&bull;")
    price_html = f'<div class="btc-side-price">{price_text}</div>' if price_text else ""

    st.markdown(
        (
            '<div class="btc-side-indicator">'
            f'<div class="btc-side-head"><div class="btc-side-label">{label}</div>{price_html}</div>'
            f'<div class="btc-side-body"><div class="btc-side-main {direction_class}"><span class="btc-side-arrow">{direction_symbol}</span><span>{change_text}</span></div></div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_app_table(rows: list[dict[str, Any]], emphasize_first_column: bool = False) -> None:
    if not rows:
        return

    columns: list[Any] = []
    for row in rows:
        for key in row.keys():
            if key not in columns:
                columns.append(key)

    frame = pd.DataFrame([{column: row.get(column, "") for column in columns} for row in rows])
    if emphasize_first_column and columns:
        styler = frame.style.set_properties(
            subset=pd.IndexSlice[:, [columns[0]]],
            **{"font-weight": "700"},
        )
        st.dataframe(styler, width="stretch", hide_index=True)
        return
    st.dataframe(frame, width="stretch", hide_index=True)


def render_ops_strip(items: list[dict], tone: str = "overview") -> None:
    item_html = []
    for item in items:
        label = escape_html_text(item.get("label", ""))
        value = escape_html_text(item.get("value", ""))
        subtitle = escape_html_text(item.get("subtitle", ""))
        if not label or not value:
            continue
        sub_html = f'<div class="ops-strip-sub">{subtitle}</div>' if subtitle else ""
        item_html.append(
            (
                '<div class="ops-strip-item">'
                f'<div class="ops-strip-label">{label}</div>'
                f'<div class="ops-strip-value">{value}</div>'
                f"{sub_html}"
                "</div>"
            )
        )
    if not item_html:
        return
    st.markdown(
        f'<div class="ops-strip ops-tone-{tone}">{"".join(item_html)}</div>',
        unsafe_allow_html=True,
    )


def render_ops_kpi_row(items: list[dict], tone: str = "balance") -> None:
    item_html = []
    for item in items:
        label = escape_html_text(item.get("label", ""))
        value = escape_html_text(item.get("value", ""))
        subtitle = escape_html_text(item.get("subtitle", ""))
        if not label or not value:
            continue
        item_html.append(
            (
                f'<div class="ops-kpi ops-tone-{tone}">'
                f'<div class="ops-kpi-label">{label}</div>'
                f'<div class="ops-kpi-value">{value}</div>'
                f'<div class="ops-kpi-sub">{subtitle}</div>'
                "</div>"
            )
        )
    if not item_html:
        return
    st.markdown(
        f'<div class="ops-kpi-row">{"".join(item_html)}</div>',
        unsafe_allow_html=True,
    )


def render_ops_inline_note(label: str, value: str) -> None:
    if not str(label or "").strip() or not str(value or "").strip():
        return
    value_text = str(value)
    replacements = {
        "Zhrnutie": "Zhrnutie",
        "Posledny sync": "Posledna synchronizacia",
        "trading_enabled": "Obchodovanie",
        "kill_switch": "Bezpecnostna ochrana",
        "Prepocet z": "Posledne vyhodnotenie z",
        "Odporucana akcia": "Odporucanie",
        "Cielovy asset": "Cielove aktivum",
        "Kriticke info": "Dolezite informacie",
    }
    for old_text, new_text in replacements.items():
        value_text = value_text.replace(old_text, new_text)
    st.markdown(
        (
            '<div class="ops-inline-note">'
            f'<span class="ops-inline-note-label">{escape_html_text(label)}</span>'
            f'<span class="ops-inline-note-value">{escape_html_text(value_text)}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_ops_dense_panel(title: str, items: list[dict], tone: str = "detail") -> None:
    chip_html = []
    for item in items:
        label = escape_html_text(item.get("label", ""))
        value = escape_html_text(item.get("value", ""))
        subtitle = escape_html_text(item.get("subtitle", ""))
        if not label or not value or value in {"0", "0.0"}:
            continue
        sub_html = f'<div class="ops-chip-sub">{subtitle}</div>' if subtitle else ""
        chip_html.append(
            (
                '<div class="ops-chip">'
                f'<div class="ops-chip-label">{label}</div>'
                f'<div class="ops-chip-value">{value}</div>'
                f"{sub_html}"
                "</div>"
            )
        )
    if not chip_html:
        return
    st.markdown(
        (
            f'<div class="ops-panel ops-tone-{tone}">'
            '<div class="ops-panel-header">'
            f'<div class="ops-panel-title">{escape_html_text(title)}</div>'
            "</div>"
            f'<div class="ops-chip-grid">{"".join(chip_html)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_ops_detail_panel(title: str, items: list[tuple[str, str]], tone: str = "detail", note: str = "") -> None:
    detail_html = []
    for label, value in items:
        detail_html.append(
            (
                '<div class="ops-detail-item">'
                f'<div class="ops-detail-label">{escape_html_text(label)}</div>'
                f'<div class="ops-detail-value">{escape_html_text(value)}</div>'
                "</div>"
            )
        )
    note_html = f'<div class="ops-inline-note">{escape_html_text(note)}</div>' if note else ""
    st.markdown(
        (
            f'<div class="ops-panel ops-tone-{tone}">'
            '<div class="ops-panel-header">'
            f'<div class="ops-panel-title">{escape_html_text(title)}</div>'
            "</div>"
            f'<div class="ops-detail-grid">{"".join(detail_html)}</div>'
            f"{note_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_story_panel(
    title: str,
    body: str,
    *,
    eyebrow: str = "",
    tone: str = "cool",
) -> None:
    eyebrow_html = f'<div class="story-eyebrow">{escape_html_text(eyebrow)}</div>' if eyebrow else ""
    st.markdown(
        (
            f'<div class="story-panel story-{tone}">'
            f"{eyebrow_html}"
            f'<div class="story-title">{escape_html_text(title)}</div>'
            f'<div class="story-body">{escape_html_text(body)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_story_list_panel(
    title: str,
    items: list[str],
    *,
    eyebrow: str = "",
    tone: str = "warm",
) -> None:
    cleaned_items = [escape_html_text(item) for item in items if str(item or "").strip()]
    if not cleaned_items:
        return
    eyebrow_html = f'<div class="story-eyebrow">{escape_html_text(eyebrow)}</div>' if eyebrow else ""
    list_html = "".join(f"<li>{item}</li>" for item in cleaned_items)
    st.markdown(
        (
            f'<div class="story-panel story-{tone}">'
            f"{eyebrow_html}"
            f'<div class="story-title">{escape_html_text(title)}</div>'
            f'<ul class="story-list">{list_html}</ul>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


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


def load_benchmark_df(path_str: str | None) -> pd.DataFrame:
    path = normalize_path(path_str)
    if path is None or not path.exists():
        raise FileNotFoundError(f"Missing benchmark source path: {path_str}")

    df = pd.read_csv(path)
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
    return df.drop_duplicates(subset=["ts"], keep="last").reset_index(drop=True)


def build_csv_btc_side_indicator_data(btc_df: pd.DataFrame) -> dict[str, Any]:
    if btc_df is None or btc_df.empty or "close" not in btc_df.columns:
        return {}

    closed_btc = btc_df.dropna(subset=["ts", "close"]).copy()
    closed_btc["ts"] = pd.to_datetime(closed_btc["ts"], errors="coerce").dt.normalize()
    closed_btc = (
        closed_btc.dropna(subset=["ts", "close"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
    )
    current_utc_day = pd.Timestamp(datetime.now(timezone.utc).date())
    closed_btc = closed_btc[closed_btc["ts"] < current_utc_day].tail(2).reset_index(drop=True)
    if len(closed_btc) < 2:
        return {}

    latest_close = as_float(closed_btc.iloc[1]["close"])
    if latest_close in (None, 0):
        return {}

    previous_close = as_float(closed_btc.iloc[0]["close"])
    display_price = latest_close
    pct_change = ((latest_close / previous_close) - 1.0) * 100.0 if previous_close not in (None, 0) else 0.0
    if pct_change is None:
        pct_change = 0.0
    return {
        "label": "BTC",
        "direction": "up" if pct_change >= 0 else "down",
        "change_text": f"{pct_change:+.2f}%",
        "price_text": f"${display_price:,.0f}",
    }


@st.cache_data(ttl=20, show_spinner=False)
def fetch_realtime_btc_ticker() -> dict[str, float] | None:
    try:
        request = Request(BTC_REALTIME_TICKER_URL, headers={"User-Agent": "TrendAtlas Crypto"})
        with urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    bitcoin_payload = payload.get("bitcoin")
    if not isinstance(bitcoin_payload, dict):
        return None

    price = as_float(bitcoin_payload.get("usd"))
    pct_change = as_float(bitcoin_payload.get("usd_24h_change"))
    if price is None or pct_change is None:
        return None
    return {"price": price, "pct_change": pct_change}


def build_btc_side_indicator_data(_btc_df: pd.DataFrame | None = None) -> dict[str, Any]:
    live_ticker = fetch_realtime_btc_ticker()
    if not live_ticker:
        return build_csv_btc_side_indicator_data(_btc_df)

    display_price = live_ticker["price"]
    pct_change = live_ticker["pct_change"]
    return {
        "label": "BTC",
        "direction": "up" if pct_change >= 0 else "down",
        "change_text": f"{pct_change:+.2f}%",
        "price_text": f"${display_price:,.0f}",
    }


def resolve_model_source(selector_cfg: dict, model_key: str) -> dict:
    model_sources = selector_cfg.get("model_sources", {}) or {}
    return dict(model_sources.get(model_key, {}) or {})


def load_paper_frame(path: Path, model_key: str) -> pd.DataFrame:
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
        df.dropna(subset=["ts"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    df.attrs["source_path"] = str(path)
    return df


def build_production_trend_live(
    snapshot: dict[str, Any],
    timeseries_df: pd.DataFrame,
) -> dict[str, Any]:
    last_row = sanitize_row_dict(timeseries_df.iloc[-1].to_dict())
    previous_row = sanitize_row_dict(timeseries_df.iloc[-2].to_dict()) if len(timeseries_df) > 1 else {}
    trend_score = as_float(snapshot.get("trend_score"))
    buy_threshold = as_float(
        first_present_value(
            last_row.get("trend_activation_threshold"),
            last_row.get("buy_threshold"),
        )
    )
    previous_trend_score = as_float(previous_row.get("trend_score"))

    crossed_up_today = (
        previous_trend_score is not None
        and trend_score is not None
        and buy_threshold is not None
        and previous_trend_score < buy_threshold <= trend_score
    )
    crossed_down_today = (
        previous_trend_score is not None
        and trend_score is not None
        and buy_threshold is not None
        and previous_trend_score > buy_threshold >= trend_score
    )

    return {
        "trend_score": trend_score,
        "buy_threshold": buy_threshold,
        "trend_state_label": snapshot.get("trend_state"),
        "trend_calc_date": snapshot.get("closed_day"),
        "crossed_up_today": crossed_up_today,
        "crossed_down_today": crossed_down_today,
    }


def build_production_trend_history(timeseries_df: pd.DataFrame) -> pd.DataFrame:
    threshold_column = (
        "trend_activation_threshold"
        if "trend_activation_threshold" in timeseries_df.columns
        else "buy_threshold"
    )
    history = timeseries_df[["ts", "trend_score", threshold_column]].copy()
    history = history.rename(columns={threshold_column: "buy_threshold"})
    history = history.dropna(subset=["ts", "trend_score", "buy_threshold"]).reset_index(drop=True)
    return history


PUBLIC_INTERNAL_CASH_ASSET_LABELS = {
    "BASE",
    "BASELINE",
    "CORE",
    "BASELINE_RISK",
    "EARLY_RISK",
    "FULL_RISK",
    "ZAKLADNA ZLOZKA",
    "ZAKLADNA_ZLOZKA",
    "ZAKLADNA-ZLOZKA",
    "ZÁKLADNÁ ZLOŽKA",
}


def normalize_public_asset_code(asset_code: Any) -> str:
    asset = str(asset_code or "").strip().upper()
    if asset in PUBLIC_INTERNAL_CASH_ASSET_LABELS:
        return "CASH"
    return asset


def product_asset_label(asset_code: Any, lang: str) -> str:
    asset = normalize_public_asset_code(asset_code)
    if asset in {"", "NONE"}:
        return t(lang, "na")
    if asset == "OUT_OF_MARKET":
        return "mimo trhu" if lang == "sk" else "out of market"
    if asset == "CASH":
        return "hotovosti" if lang == "sk" else "cash"
    if asset == "BTC":
        return "BTC"
    return asset


def product_asset_label_nominative(asset_code: Any, lang: str) -> str:
    asset = normalize_public_asset_code(asset_code)
    if asset == "OUT_OF_MARKET":
        return "Mimo trhu" if lang == "sk" else "Out of market"
    if asset == "CASH":
        return "Hotovosť" if lang == "sk" else "Cash"
    if asset == "BTC":
        return "BTC"
    return asset or t(lang, "na")


def _sk_reason_code_label(reason_code: str) -> str:
    mapping = {
        "rebalance_to_cash": "presun do hotovosti",
        "rebalance_to_btc": "presun do BTC",
        "rebalance_to_base": "presun do zakladnej zlozky",
        "trend_gate_hold": "cakanie na silnejsi trend",
        "candidate_wait_trend_confirmation": "cakanie na potvrdenie trendu pre vstup",
        "entry_buffer_hold": "povinne potvrdenie po zmene",
        "hold_cash": "zotrvanie v hotovosti",
    }
    return mapping.get(reason_code, "zmena signaloveho stavu")


def humanize_production_pain_point(pain_point: dict[str, Any], lang: str) -> str:
    code = str(pain_point.get("code") or "").strip().lower()
    metric_value = as_float(pain_point.get("metric_value"))
    if lang == "sk":
        if code == "cash_drag_elevated" and metric_value is not None:
            return f"Strategia travi v hotovosti velku cast historie ({metric_value:.2f} %), co tlmi rast v silnych trhoch."
        if code == "lifetime_cost_drag_elevated" and metric_value is not None:
            return f"Historicke naklady uz ubrali zhruba {metric_value:.2f} % vykonu, takze kazda zbytocna zmena boli viac."
        if code == "trend_entry_not_confirmed":
            return "Vybrane aktivum este nema potvrdeny vstup do trhu, preto zostava strategia mimo trhu."
        if code == "active_wait_condition":
            return "Strategia ma vybrane aktivum, ale zatial nema potvrdeny bezpecny vstup do trhu."
        return "Strategia zatial nema potvrdeny dost silny signal na novu trhovu expoziciu."
    return str(pain_point.get("text") or "").strip()


def production_market_state_label_from_values(
    exposure: Any,
    trend_permission_active: Any,
    lang: str,
) -> str:
    exposure_value = as_float(exposure)
    permission_active = as_bool(trend_permission_active)
    if permission_active is True and exposure_value is not None and not math.isclose(exposure_value, 0.0, abs_tol=1e-12):
        return t(lang, "production_hover_market_state_in")
    return t(lang, "production_hover_market_state_out")


def production_market_state_label(
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    lang: str,
) -> str:
    trade_state = dict(diagnostics.get("current_trade_state") or {})
    trend_permission_active = as_bool(
        first_present_value(
            trade_state.get("trend_permission_active"),
            snapshot.get("trend_permission_active"),
        )
    )
    exposure = as_float(
        first_present_value(
            trade_state.get("effective_market_exposure"),
            snapshot.get("effective_market_exposure"),
            snapshot.get("current_exposure"),
        )
    )
    market_state = production_market_state_label_from_values(
        exposure=exposure,
        trend_permission_active=trend_permission_active,
        lang=lang,
    )
    if market_state == t(lang, "production_hover_market_state_in"):
        return t(lang, "production_state_in_market")
    return t(lang, "production_state_out_of_market")


def _first_numeric_value(*values: Any) -> float | None:
    for value in values:
        number = as_float(value)
        if number is not None:
            return number
    return None


def resolve_real_account_exposure_state(
    *,
    account_snapshot_view: dict[str, Any],
    dry_run_decision_payload: dict[str, Any],
    real_order_gate_payload: dict[str, Any],
    production_snapshot: dict[str, Any],
    lang: str,
    runtime_real_account_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(runtime_real_account_state, dict) and runtime_real_account_state:
        asset = str(runtime_real_account_state.get("asset") or "CASH").strip().upper() or "CASH"
        exposure_value = as_float(runtime_real_account_state.get("exposure_x"))
        if exposure_value is None:
            exposure_value = 0.0
        in_market = as_bool(runtime_real_account_state.get("in_market")) is True
        state_text = (
            t(lang, "production_state_in_market")
            if in_market
            else t(lang, "production_state_out_of_market")
        )
        exposure_text = f"{exposure_value:.2f}x"
        gate_status = str(runtime_real_account_state.get("gate_status") or "").strip().lower()
        would_place_real_order = as_bool(runtime_real_account_state.get("would_place_real_order"))
        subtitle = (
            "CASH | Odoslanie obchodu blokovane"
            if lang == "sk" and (gate_status == "blocked" or would_place_real_order is False)
            else "CASH | Order placement blocked"
            if gate_status == "blocked" or would_place_real_order is False
            else str(runtime_real_account_state.get("source") or "wallet/intent/gate")
        )
        return {
            "is_out_of_market": not in_market,
            "asset": asset,
            "exposure": exposure_value,
            "exposure_text": exposure_text,
            "state_text": state_text,
            "value": f"{state_text} / {exposure_text}",
            "subtitle": subtitle,
            "target_asset": str(runtime_real_account_state.get("intent_target_asset") or asset).strip().upper(),
            "gate_status": gate_status,
            "would_place_real_order": would_place_real_order,
        }

    open_position = (
        account_snapshot_view.get("open_position")
        if isinstance(account_snapshot_view.get("open_position"), dict)
        else None
    )
    open_position_asset = ""
    open_position_size = 0.0
    if open_position:
        open_position_asset = str(
            open_position.get("symbol") or open_position.get("asset") or open_position.get("coin") or ""
        ).strip().upper()
        open_position_size = abs(as_float(open_position.get("size")) or 0.0)

    production_signal_context = dict(real_order_gate_payload.get("production_signal_context") or {})
    production_intent = dict(production_snapshot.get("execution_intent") or {})
    target_asset = str(
        first_present_value(
            real_order_gate_payload.get("target_asset"),
            dry_run_decision_payload.get("target_asset"),
            production_signal_context.get("target_asset"),
            production_intent.get("target_asset"),
        )
        or ""
    ).strip().upper()
    target_exposure = _first_numeric_value(
        dry_run_decision_payload.get("target_size_pct"),
        dry_run_decision_payload.get("target_exposure"),
        production_signal_context.get("target_exposure"),
        production_intent.get("target_exposure"),
        real_order_gate_payload.get("target_exposure"),
    )
    gate_status = str(real_order_gate_payload.get("status") or "").strip().lower()
    would_place_real_order = as_bool(real_order_gate_payload.get("would_place_real_order"))
    account_has_open_position = bool(open_position_asset and open_position_size > 1e-12)

    if account_has_open_position:
        exposure_value = _first_numeric_value(
            account_snapshot_view.get("current_exposure"),
            target_exposure,
            production_signal_context.get("effective_market_exposure"),
            production_snapshot.get("effective_market_exposure"),
        )
        exposure_text = f"{exposure_value:.2f}x" if exposure_value is not None else t(lang, "na")
        state_text = t(lang, "production_state_in_market")
        subtitle = (
            f"Otvorena pozicia: {open_position_asset}"
            if lang == "sk"
            else f"Open position: {open_position_asset}"
        )
        return {
            "is_out_of_market": False,
            "asset": open_position_asset,
            "exposure": exposure_value,
            "exposure_text": exposure_text,
            "state_text": state_text,
            "value": f"{state_text} / {exposure_text}",
            "subtitle": subtitle,
            "target_asset": target_asset,
            "gate_status": gate_status,
            "would_place_real_order": would_place_real_order,
        }

    execution_points_to_cash = (
        target_asset in {"", "CASH", "USD", "USDC", "USDT", "NONE", "NULL"}
        or (target_exposure is not None and math.isclose(target_exposure, 0.0, abs_tol=1e-12))
        or gate_status == "blocked"
        or would_place_real_order is False
    )
    if execution_points_to_cash:
        state_text = t(lang, "production_state_out_of_market")
        exposure_text = "0.00x"
        ordering_blocked = gate_status == "blocked" or would_place_real_order is False
        subtitle = (
            "CASH | Odoslanie obchodu blokovane"
            if lang == "sk" and ordering_blocked
            else "CASH | Podla uctu a vykonavacich kontrol"
            if lang == "sk"
            else "CASH | Order placement blocked"
            if ordering_blocked
            else "CASH | Based on account and execution checks"
        )
        return {
            "is_out_of_market": True,
            "asset": "CASH",
            "exposure": 0.0,
            "exposure_text": exposure_text,
            "state_text": state_text,
            "value": f"{state_text} / {exposure_text}",
            "subtitle": subtitle,
            "target_asset": target_asset or "CASH",
            "gate_status": gate_status,
            "would_place_real_order": would_place_real_order,
        }

    state_text = t(lang, "production_state_out_of_market")
    exposure_text = "0.00x"
    return {
        "is_out_of_market": True,
        "asset": "CASH",
        "exposure": 0.0,
        "exposure_text": exposure_text,
        "state_text": state_text,
        "value": f"{state_text} / {exposure_text}",
        "subtitle": (
            "Signal este nie je otvorena pozicia na ucte"
            if lang == "sk"
            else "Signal is not yet an open account position"
        ),
        "target_asset": target_asset,
        "gate_status": gate_status,
        "would_place_real_order": would_place_real_order,
    }


def production_wait_reason_short(
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    lang: str,
) -> str:
    trade_state = dict(diagnostics.get("current_trade_state") or {})
    trend_permission_active = as_bool(
        first_present_value(
            trade_state.get("trend_permission_active"),
            snapshot.get("trend_permission_active"),
        )
    )
    if trend_permission_active is not True:
        return t(lang, "production_wait_reason_pending")
    return t(lang, "production_wait_reason_active")


def build_production_chart_current_state_note(
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    lang: str,
    real_account_exposure_state: dict[str, Any] | None = None,
    model_signal_state: dict[str, Any] | None = None,
) -> str:
    model_state = model_signal_state or {}
    candidate_asset = product_asset_label_nominative(
        first_present_value(model_state.get("preferred_asset"), snapshot.get("candidate_asset"), snapshot.get("selected_asset")),
        lang,
    )
    real_state = real_account_exposure_state or {}
    if real_state.get("is_out_of_market") is True:
        exposure_text = str(real_state.get("exposure_text") or "0.00x")
        return (
            f"Aktualne je realny ucet mimo trhu s expoziciou {exposure_text}. Model preferuje {candidate_asset}, ale graf nie je vypis otvorenej pozicie."
            if lang == "sk"
            else f"The real account is currently out of market with {exposure_text} exposure. The model prefers {candidate_asset}, but the chart is not an open-position statement."
        )
    exposure = as_float(
        first_present_value(
            model_state.get("exposure_x"),
        )
    )
    exposure_text = f"{exposure:.2f}x" if exposure is not None else t(lang, "na")
    market_state = production_market_state_label(snapshot, diagnostics, lang)
    if market_state == t(lang, "production_state_out_of_market"):
        return t(lang, "production_chart_current_out_note").format(
            candidate=candidate_asset,
            exposure=exposure_text,
        )
    return t(lang, "production_chart_current_in_note").format(
        candidate=candidate_asset,
        exposure=exposure_text,
    )


def build_homepage_state_story(
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    lang: str,
    real_account_exposure_state: dict[str, Any] | None = None,
    model_signal_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_state = model_signal_state or {}
    trade_state = dict(diagnostics.get("current_trade_state") or {})
    candidate_asset = str(
        first_present_value(
            model_state.get("preferred_asset"),
            trade_state.get("candidate_asset"),
            snapshot.get("candidate_asset"),
            snapshot.get("selected_asset"),
        )
        or ""
    ).strip().upper()
    actual_asset = str(
        first_present_value(
            trade_state.get("actual_held_asset"),
            snapshot.get("actual_held_asset"),
            snapshot.get("current_asset"),
        )
        or ""
    ).strip().upper()
    exposure = as_float(
        first_present_value(
            model_state.get("exposure_x"),
        )
    )
    candidate_exposure = as_float(
        first_present_value(
            model_state.get("exposure_x"),
            trade_state.get("model_candidate_exposure"),
            snapshot.get("model_candidate_exposure"),
        )
    )
    trend_permission_active = as_bool(
        first_present_value(
            trade_state.get("trend_permission_active"),
            snapshot.get("trend_permission_active"),
        )
    )
    exposure_text = f"{exposure:.2f}x" if exposure is not None else t(lang, "na")
    candidate_exposure_text = (
        f"{candidate_exposure:.2f}x" if candidate_exposure is not None else t(lang, "na")
    )
    wait_condition = dict(diagnostics.get("current_wait_condition") or {})
    current_values = dict(wait_condition.get("current_values") or {})
    target_condition = dict(wait_condition.get("target_condition") or {})
    trend_score = as_float(first_present_value(current_values.get("trend_score"), snapshot.get("trend_score")))
    trend_score_text = f"{trend_score:.4f}" if trend_score is not None else t(lang, "na")
    threshold = as_float(
        first_present_value(
            target_condition.get("trend_score_min"),
            current_values.get("trend_activation_threshold"),
        )
    )
    threshold_text = f"{threshold:.4f}" if threshold is not None else t(lang, "na")
    latest_rebalance_date = get_nested_value(snapshot, "decision_context", "latest_rebalance_date")
    latest_rebalance_reason = str(get_nested_value(snapshot, "decision_context", "latest_rebalance_reason") or "").strip().lower()
    pain_points = list(diagnostics.get("current_pain_points") or [])
    candidate_label = product_asset_label_nominative(candidate_asset, lang)
    actual_label = product_asset_label_nominative(actual_asset, lang)
    is_out_of_market = trend_permission_active is not True or exposure is None or math.isclose(exposure, 0.0, abs_tol=1e-12)
    real_state = real_account_exposure_state or {}
    real_account_is_out = real_state.get("is_out_of_market") is True
    real_exposure_text = str(real_state.get("exposure_text") or "0.00x")

    if lang == "sk":
        if real_account_is_out:
            now_text = (
                f"Realny ucet je mimo trhu s expoziciou {real_exposure_text}. "
                f"Model momentalne preferuje {candidate_label}, ale tento signal nie je otvorena pozicia na ucte."
            )
        elif is_out_of_market:
            now_text = (
                f"Preferovane aktivum je {candidate_label}, ale strategia je momentalne mimo trhu. "
                f"Aktualna trhova expozicia je {exposure_text}."
            )
        else:
            now_text = (
                f"Modelovy signal je momentalne aktivny s velkostou "
                f"{exposure_text} v aktive {actual_label}."
            )

        if real_account_is_out:
            why_text = (
                "Vstup nie je povoleny vykonavacimi kontrolami, preto realny ucet zostava mimo trhu."
            )
        elif is_out_of_market and trend_score is not None and threshold is not None:
            why_text = (
                f"Dovod je jednoduchy: trend zatial nepotvrdil vstup. Dnesny trend score je "
                f"{trend_score_text}, kym potrebna hranica je {threshold_text}."
            )
        elif trend_score is not None and threshold is not None:
            why_text = (
                f"Trend score je {trend_score_text}, teda nad rozhodujucou hranicou {threshold_text}. "
                f"Preto je modelovy signal povoleny."
            )
        else:
            why_text = "Aktualny signal zatial nepotvrdil dovod na zmenu modelovej trhovej expozicie."

        wait_text = (
            f"Cakame na trend_score >= {threshold_text}. Az potom moze strategia povolit vstup do {candidate_label}."
            if is_out_of_market and threshold is not None
            else "Aktualne necaka na potvrdenie vstupu. Caka len na dalsi validovany signal alebo novy rebalance."
        )

        change_text = (
            f"Ak trend score vystupi aspon na {threshold_text}, preferovane aktivum {candidate_label} sa moze zmenit na realnu "
            f"trhovu expoziciu s cielovou velkostou {candidate_exposure_text}."
            if is_out_of_market and threshold is not None
            else "Spravanie sa zmeni az po potvrdeni noveho signalu, noveho rebalance alebo vypnutia aktualnej expozicie."
        )

        risk_items = [humanize_production_pain_point(item, lang) for item in pain_points]
        if latest_rebalance_date:
            risk_items.append(
                f"Posledna vacsia zmena prisla {format_date_text(latest_rebalance_date, lang)} ako {_sk_reason_code_label(latest_rebalance_reason)}."
            )
        return {
            "now": now_text,
            "why": why_text,
            "wait": wait_text,
            "change": change_text,
            "risks": risk_items,
        }

    return {
        "now": (
            f"The real account is out of market with {real_exposure_text} exposure. The model currently prefers {candidate_label}, but that signal is not an open account position."
            if real_account_is_out
            else
            f"The preferred asset is {candidate_label}, but the strategy stays out of market with {exposure_text} exposure."
            if is_out_of_market
            else f"The strategy is in market with {exposure_text} exposure to {actual_label}."
        ),
        "why": (
            "Execution checks do not allow market entry, so the real account remains out of market."
            if real_account_is_out
            else
            f"Trend has not confirmed entry yet ({trend_score_text} vs {threshold_text})."
            if is_out_of_market and threshold is not None
            else "The current exposure is authorized by the latest validated signal."
        ),
        "wait": (
            f"Waiting for trend_score >= {threshold_text} before entering {candidate_label}."
            if is_out_of_market and threshold is not None
            else "Waiting for the next validated signal or rebalance."
        ),
        "change": "Behavior changes only after a stronger signal or a new rebalance is confirmed.",
        "risks": [humanize_production_pain_point(item, lang) for item in pain_points],
    }


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


def clip_homepage_chart_frames(
    main_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    year: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.Timestamp]]:
    main_plot = filter_from_year(main_df, year).copy()
    btc_plot = filter_from_year(btc_df, year).dropna(subset=["ts", "close"]).copy()
    if main_plot.empty:
        raise ValueError("homepage main chart has no main strategy rows for the selected year")
    if btc_plot.empty:
        raise ValueError("homepage main chart has no BTC benchmark rows for the selected year")

    main_plot["ts"] = pd.to_datetime(main_plot["ts"], errors="coerce").dt.normalize()
    btc_plot["ts"] = pd.to_datetime(btc_plot["ts"], errors="coerce").dt.normalize()
    main_plot = (
        main_plot.dropna(subset=["ts"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    btc_plot = (
        btc_plot.dropna(subset=["ts", "close"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )

    visible_start = max(main_plot["ts"].min(), btc_plot["ts"].min())
    visible_end = min(main_plot["ts"].max(), btc_plot["ts"].max())
    if pd.isna(visible_start) or pd.isna(visible_end) or visible_start > visible_end:
        raise ValueError(
            "homepage main chart has no overlapping visible date window for the selected year"
        )

    main_plot = main_plot[
        (main_plot["ts"] >= visible_start) & (main_plot["ts"] <= visible_end)
    ].copy()
    btc_plot = btc_plot[
        (btc_plot["ts"] >= visible_start) & (btc_plot["ts"] <= visible_end)
    ].copy()
    if main_plot.empty or btc_plot.empty:
        raise ValueError(
            "homepage main chart has no overlapping visible date window for the selected year"
        )

    null_equity_rows = main_plot["equity"].isna()
    if null_equity_rows.any():
        bad_dates = (
            main_plot.loc[null_equity_rows, "ts"]
            .dt.strftime("%Y-%m-%d")
            .head(5)
            .tolist()
        )
        raise ValueError(
            "homepage main chart aborted because the visible main strategy horizon "
            f"contains null equity rows: {bad_dates}"
        )

    main_plot = main_plot.dropna(subset=["equity"]).copy()

    return main_plot, btc_plot, {"start": visible_start, "end": visible_end}


def rebase_series(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    first_valid = s.dropna()
    if first_valid.empty:
        return s
    return s / first_valid.iloc[0]


def homepage_cash_mask(df: pd.DataFrame) -> pd.Series:
    if "cash_day" in df.columns:
        cash_values = df["cash_day"].map(as_bool)
        if cash_values.notna().any():
            return cash_values.fillna(False).astype(bool)

    for col in ["portfolio_held_asset", "held_asset", "baseline_held_asset"]:
        if col not in df.columns:
            continue
        assets = df[col].fillna("").astype(str).str.strip().str.upper()
        return assets.isin({"", "CASH", "USD", "USDT", "NONE", "NULL"})

    return pd.Series(False, index=df.index, dtype=bool)


def normalize_homepage_chart_asset_token(value: Any) -> str:
    if value is None:
        return ""
    numeric = as_float(value)
    if numeric is not None:
        if math.isclose(numeric, 0.0, abs_tol=1e-12):
            return "CASH"
        return ""
    return str(value).strip().upper()


def homepage_chart_daily_return_series(df: pd.DataFrame) -> pd.Series:
    for col in ["realistic_ret", "realistic_ret_gross", "base_ret"]:
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce")
    return pd.Series([math.nan] * len(df), index=df.index, dtype="float64")


def homepage_chart_semantic_cash_like(row: pd.Series) -> bool:
    if as_bool(row.get("cash_day")) is True:
        return True

    no_movement_reasons = {
        "CASH",
        "SWITCH_DAY",
        "ENTRY_BUFFER_DAY",
        "STRESS_BLOCK",
        "TREND_GATE",
    }
    reason = normalize_homepage_chart_asset_token(row.get("leverage_state_reason"))
    equity_delta = as_float(row.get("equity_delta"))
    daily_return = as_float(row.get("daily_return_used"))
    zero_equity_delta = equity_delta is not None and math.isclose(equity_delta, 0.0, abs_tol=1e-12)
    zero_daily_return = daily_return is not None and math.isclose(daily_return, 0.0, abs_tol=1e-12)
    if reason in no_movement_reasons and (zero_equity_delta or zero_daily_return):
        return True

    return False


def homepage_chart_state_details(df: pd.DataFrame, lang: str) -> pd.DataFrame:
    state_df = df.copy().reset_index(drop=True)
    state_df["ts"] = pd.to_datetime(state_df["ts"], errors="coerce").dt.normalize()
    state_df["equity_delta"] = pd.to_numeric(state_df.get("equity"), errors="coerce").diff()
    state_df["daily_return_used"] = homepage_chart_daily_return_series(state_df)
    cash_mask = homepage_cash_mask(state_df).reset_index(drop=True)
    bucket_values: list[str] = []
    label_values: list[str] = []
    semantic_cash_like_values: list[bool] = []

    candidate_columns = [
        "portfolio_held_asset",
        "held_asset",
        "executed_position",
        "tradable_governed_asset",
        "baseline_held_asset",
        "executed_regime",
    ]

    for idx, row in state_df.iterrows():
        asset_token = ""
        for col in candidate_columns:
            if col not in state_df.columns:
                continue
            candidate = normalize_homepage_chart_asset_token(row.get(col))
            if candidate in {"", "NONE", "NULL"}:
                continue
            asset_token = candidate
            break

        semantic_cash_like = bool(cash_mask.iloc[idx]) or homepage_chart_semantic_cash_like(row)
        if semantic_cash_like:
            bucket = "CASH"
            label = t(lang, "chart_state_cash")
        elif asset_token in {"BASE", "BASELINE", "BASELINE_RISK", "EARLY_RISK", "FULL_RISK"}:
            bucket = "CASH"
            label = t(lang, "chart_state_cash")
        elif asset_token == "BTC":
            bucket = "BTC"
            label = t(lang, "chart_state_btc")
        elif asset_token in {"", "CASH", "USD", "USDT", "NONE", "NULL", "ZERO", "ZERO_EXPOSURE"}:
            bucket = "CASH"
            label = t(lang, "chart_state_cash")
        else:
            bucket = "ALT"
            label = f"{t(lang, 'chart_state_alt')} · {prettify_asset_public(asset_token, lang)}"

        bucket_values.append(bucket)
        label_values.append(label)
        semantic_cash_like_values.append(semantic_cash_like)

    state_df["state_bucket"] = bucket_values
    state_df["state_label"] = label_values
    state_df["semantic_cash_like"] = semantic_cash_like_values
    return state_df[["ts", "state_bucket", "state_label", "semantic_cash_like"]].dropna(subset=["ts"]).copy()


def build_homepage_chart_truth_warnings(state_df: pd.DataFrame) -> list[str]:
    if state_df.empty or "semantic_cash_like" not in state_df.columns:
        return []

    mismatches = state_df[
        state_df["semantic_cash_like"].fillna(False).astype(bool)
        & (state_df["state_bucket"].astype(str) != "CASH")
    ].copy()
    if mismatches.empty:
        return []

    dates = mismatches["ts"].dt.strftime("%Y-%m-%d").head(5).tolist()
    return [
        "Varovanie: spodny pas grafu bol zablokovany, pretoze drzane stavy "
        "momentalne nie je mozne zobrazit spolahlivo "
        f"na datumoch: {', '.join(dates)}."
    ]


def homepage_chart_has_material_movement(row: pd.Series) -> bool:
    equity_delta = as_float(row.get("equity_delta"))
    daily_return = as_float(row.get("daily_return_used"))
    if equity_delta is not None and not math.isclose(equity_delta, 0.0, abs_tol=1e-12):
        return True
    if daily_return is not None and not math.isclose(daily_return, 0.0, abs_tol=1e-12):
        return True
    return False


def homepage_chart_truthful_strip_source_column(df: pd.DataFrame) -> str | None:
    trusted_columns = ["held_asset_public", "portfolio_held_asset", "held_asset", "executed_position"]
    candidate_values: dict[str, pd.Series] = {}

    for col in trusted_columns:
        if col not in df.columns:
            continue
        normalized = df[col].map(normalize_homepage_chart_asset_token)
        meaningful = normalized[~normalized.isin({"", "NONE", "NULL"})]
        if meaningful.empty:
            continue
        candidate_values[col] = normalized

    if not candidate_values:
        return None

    for idx in df.index:
        row_values = {
            values.loc[idx]
            for values in candidate_values.values()
            if values.loc[idx] not in {"", "NONE", "NULL"}
        }
        if len(row_values) > 1:
            return None

    return next(iter(candidate_values))


def homepage_chart_is_cash_token(token: str) -> bool:
    return token in {
        "",
        "CASH",
        "USD",
        "USDT",
        "NONE",
        "NULL",
        "ZERO",
        "ZERO_EXPOSURE",
        "BASE",
        "BASELINE",
        "CORE",
        "BASELINE_RISK",
        "EARLY_RISK",
        "FULL_RISK",
    }


def build_truthful_homepage_chart_state_details(df: pd.DataFrame, lang: str) -> pd.DataFrame:
    state_df = df.copy().reset_index(drop=True)
    state_df["ts"] = pd.to_datetime(state_df["ts"], errors="coerce").dt.normalize()
    state_df["equity_delta"] = pd.to_numeric(state_df.get("equity"), errors="coerce").diff()
    state_df["daily_return_used"] = homepage_chart_daily_return_series(state_df)

    source_column = homepage_chart_truthful_strip_source_column(state_df)
    if source_column is None:
        return pd.DataFrame(columns=["ts", "state_bucket", "state_label"])

    source_tokens = state_df[source_column].map(normalize_homepage_chart_asset_token)
    if source_tokens.isin({"", "NONE", "NULL"}).any():
        return pd.DataFrame(columns=["ts", "state_bucket", "state_label"])

    cash_day_values = state_df["cash_day"].map(as_bool) if "cash_day" in state_df.columns else None
    bucket_values: list[str] = []
    label_values: list[str] = []

    for idx, token in source_tokens.items():
        token_is_cash = homepage_chart_is_cash_token(token)
        if token_is_cash and homepage_chart_has_material_movement(state_df.loc[idx]):
            return pd.DataFrame(columns=["ts", "state_bucket", "state_label"])
        if cash_day_values is not None:
            cash_flag = cash_day_values.loc[idx]
            if cash_flag is True and not token_is_cash:
                return pd.DataFrame(columns=["ts", "state_bucket", "state_label"])
            if cash_flag is False and token_is_cash:
                return pd.DataFrame(columns=["ts", "state_bucket", "state_label"])

        if token_is_cash:
            bucket_values.append("CASH")
            label_values.append(t(lang, "chart_state_cash"))
        elif token == "BTC":
            bucket_values.append("BTC")
            label_values.append(t(lang, "chart_state_btc"))
        else:
            bucket_values.append("ALT")
            label_values.append(f"{t(lang, 'chart_state_alt')} · {prettify_asset_public(token, lang)}")

    state_df["state_bucket"] = bucket_values
    state_df["state_label"] = label_values
    return state_df[["ts", "state_bucket", "state_label"]].dropna(subset=["ts"]).copy()


def homepage_chart_strip_is_truthful(
    main_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    year: int,
    lang: str,
) -> bool:
    try:
        main_plot, _btc_plot, _visible_window = clip_homepage_chart_frames(main_df, btc_df, year)
    except Exception:
        return False
    return not build_truthful_homepage_chart_state_details(main_plot, lang).empty


def cash_regime_spans(dates: pd.Series, cash_mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ts = pd.to_datetime(dates, errors="coerce").dt.normalize().reset_index(drop=True)
    mask = pd.Series(cash_mask, index=dates.index).fillna(False).astype(bool).reset_index(drop=True)
    spans: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    start: pd.Timestamp | None = None
    prev: pd.Timestamp | None = None

    for dt, is_cash in zip(ts, mask, strict=False):
        if pd.isna(dt):
            continue
        if is_cash and start is None:
            start = dt
        if not is_cash and start is not None:
            spans.append((start, prev if prev is not None else dt))
            start = None
        prev = dt

    if start is not None and prev is not None:
        spans.append((start, prev))

    return spans


def homepage_chart_state_periods(state_df: pd.DataFrame) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    if state_df.empty:
        return periods

    current_bucket: str | None = None
    current_label: str | None = None
    start: pd.Timestamp | None = None
    prev: pd.Timestamp | None = None

    for row in state_df.itertuples(index=False):
        dt = pd.to_datetime(row.ts, errors="coerce")
        if pd.isna(dt):
            continue

        bucket = str(row.state_bucket)
        label = str(row.state_label)
        if current_bucket is None:
            current_bucket = bucket
            current_label = label
            start = dt
        elif bucket != current_bucket or label != current_label:
            periods.append(
                {
                    "bucket": current_bucket,
                    "label": current_label,
                    "start": start,
                    "end": prev if prev is not None else dt,
                }
            )
            current_bucket = bucket
            current_label = label
            start = dt
        prev = dt

    if current_bucket is not None and current_label is not None and start is not None and prev is not None:
        periods.append(
            {
                "bucket": current_bucket,
                "label": current_label,
                "start": start,
                "end": prev,
            }
        )

    return periods


def build_homepage_chart_context_note(live_public_state: dict[str, Any], lang: str) -> str:
    label = t(lang, "chart_current_regime_label")
    if as_bool(live_public_state.get("cash_day")) is True:
        return f"{label}: {t(lang, 'chart_current_regime_cash')}"

    held_asset = resolve_homepage_held_state(live_public_state, lang)
    asset_label = prettify_asset_public(held_asset, lang)
    return f"{label}: {t(lang, 'chart_current_regime_exposed').format(asset=asset_label)}"


def build_homepage_chart_explainer_line(
    main_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    year: int,
    live_public_state: dict[str, Any],
    lang: str,
) -> str:
    try:
        main_plot, _btc_plot, _visible_window = clip_homepage_chart_frames(main_df, btc_df, year)
    except Exception:
        return build_homepage_chart_context_note(live_public_state, lang)

    state_details = build_truthful_homepage_chart_state_details(main_plot, lang)
    if state_details.empty:
        return build_homepage_chart_context_note(live_public_state, lang)

    latest_row = state_details.iloc[-1]
    latest_bucket = str(latest_row.get("state_bucket") or "").strip().upper()
    latest_label = str(latest_row.get("state_label") or "").strip()
    if latest_bucket == "CASH":
        return t(lang, "chart_visible_cash_explainer")
    if latest_label:
        return t(lang, "chart_visible_state_explainer").format(regime=latest_label)
    return build_homepage_chart_context_note(live_public_state, lang)


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
# TREND BAROMETER
# =========================================================

def coerce_trend_barometer_live_row(row: dict[str, Any]) -> dict[str, Any]:
    numeric_fields = [
        "trend_score",
        "buy_threshold",
        "prev_trend_score",
        "trend_input_raw",
        "trend_threshold_raw",
        "trend_band",
        "trend_score_raw",
        "candidate_assets_loaded",
        "failed_assets_count",
        "suspended_assets_now",
    ]
    bool_fields = ["crossed_up_today", "crossed_down_today"]
    live_row = dict(row)
    for field in numeric_fields:
        if field in live_row:
            live_row[field] = as_float(live_row.get(field))
    for field in bool_fields:
        if field in live_row:
            live_row[field] = as_bool(live_row.get(field))
    return live_row


def load_trend_barometer_history(
    source_cfg: dict,
    trend_live: dict[str, Any] | None = None,
) -> pd.DataFrame:
    path = normalize_path(source_cfg.get("history_path"))
    if path is None or not path.exists():
        df = pd.DataFrame(columns=["ts", "trend_score", "buy_threshold"])
    else:
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]

        date_col = next((c for c in ["trend_calc_date", "date", "ts", "datetime", "timestamp"] if c in df.columns), None)
        if date_col is None or "trend_score" not in df.columns:
            df = pd.DataFrame(columns=["ts", "trend_score", "buy_threshold"])
        else:
            df["ts"] = pd.to_datetime(df[date_col], errors="coerce")
            df["trend_score"] = pd.to_numeric(df["trend_score"], errors="coerce")
            if "buy_threshold" in df.columns:
                df["buy_threshold"] = pd.to_numeric(df["buy_threshold"], errors="coerce")
            else:
                df["buy_threshold"] = 0.0
            df = df.dropna(subset=["ts", "trend_score"]).sort_values("ts").reset_index(drop=True)

    if trend_live:
        live_day_text = resolve_trend_barometer_live_day(trend_live)
        live_day = pd.to_datetime(live_day_text, errors="coerce")
        live_score = as_float(trend_live.get("trend_score"))
        live_threshold = as_float(trend_live.get("buy_threshold"))
        if not pd.isna(live_day) and live_score is not None:
            live_ts = pd.Timestamp(live_day).normalize()
            if not df.empty:
                df = df[df["ts"].dt.normalize() <= live_ts].copy()
                df = df[df["ts"].dt.normalize() != live_ts]
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [
                            {
                                "ts": live_ts,
                                "trend_score": live_score,
                                "buy_threshold": live_threshold if live_threshold is not None else 0.0,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            ).sort_values("ts").reset_index(drop=True)

    return df[["ts", "trend_score", "buy_threshold"]]


def load_trend_barometer_live(source_cfg: dict) -> dict[str, Any]:
    expected_model = str(source_cfg.get("model_key") or "").strip()
    snapshot_row = source_cfg.get("authority_live_summary")
    if isinstance(snapshot_row, dict) and snapshot_row:
        row = dict(snapshot_row)
    else:
        path = normalize_path(source_cfg.get("live_status_path"))
        if path is None or not path.exists():
            raise ValueError("trend barometer canonical live status CSV is missing")
        row = load_single_csv_row(path, context="trend barometer live status")

    actual_model = str(row.get("model") or "").strip()
    if expected_model and actual_model and actual_model != expected_model:
        raise ValueError(
            "trend barometer canonical live status model diverged "
            f"(expected={expected_model} actual={actual_model})"
        )

    return coerce_trend_barometer_live_row(row)


def resolve_trend_barometer_live_day(trend_live: dict[str, Any]) -> str:
    for field in ["trend_calc_date", "latest_available_date", "date"]:
        value = trend_live.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text[:10]
    return ""


def build_trend_barometer_consistency_warnings(
    trend_live: dict[str, Any],
    history_df: pd.DataFrame,
) -> list[str]:
    if not trend_live or history_df.empty:
        return []

    warnings: list[str] = []
    history_last_row = history_df.sort_values("ts").iloc[-1]
    live_day = resolve_trend_barometer_live_day(trend_live)
    history_day = pd.to_datetime(history_last_row["ts"], errors="coerce")
    history_day_text = history_day.strftime("%Y-%m-%d") if not pd.isna(history_day) else ""
    if live_day and history_day_text and live_day != history_day_text:
        warnings.append(
            "Varovanie: Trend barometer je zablokovany, pretoze live row a mini historia "
            f"nemaju rovnaky datum ({live_day} vs {history_day_text})."
        )

    live_score = as_float(trend_live.get("trend_score"))
    history_score = as_float(history_last_row.get("trend_score"))
    if (
        live_score is not None
        and history_score is not None
        and not math.isclose(live_score, history_score, abs_tol=1e-12)
    ):
        warnings.append(
            "Varovanie: Trend barometer je zablokovany, pretoze live row a mini historia "
            "maju odlisny trend score v poslednom dni."
        )

    live_threshold = as_float(trend_live.get("buy_threshold"))
    history_threshold = as_float(history_last_row.get("buy_threshold"))
    if (
        live_threshold is not None
        and history_threshold is not None
        and not math.isclose(live_threshold, history_threshold, abs_tol=1e-12)
    ):
        warnings.append(
            "Varovanie: Trend barometer je zablokovany, pretoze live row a mini historia "
            "maju odlisny buy threshold v poslednom dni."
        )

    return warnings


# =========================================================
# CHARTS
# =========================================================

def make_capital_chart(
    main_df: pd.DataFrame,
    reference_df: pd.DataFrame | None,
    btc_df: pd.DataFrame,
    year: int,
    lang: str,
    main_label: str,
    reference_label: str,
    btc_label: str,
    title: str,
) -> go.Figure:
    del reference_df, reference_label
    main_plot, btc_plot, _visible_window = clip_homepage_chart_frames(
        main_df,
        btc_df,
        year,
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=main_plot["ts"],
            y=rebase_series(main_plot["equity"]),
            mode="lines",
            name=main_label,
            line=dict(width=4.8, color="#ff6b6b"),
        ),
    )

    fig.add_trace(
        go.Scatter(
            x=btc_plot["ts"],
            y=rebase_series(btc_plot["close"]),
            mode="lines",
            name=btc_label,
            line=dict(width=2.4, color="#60a5fa", dash="solid"),
        ),
    )

    fig.update_layout(
        height=560,
        title=title,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.015)",
        margin=dict(l=20, r=20, t=60, b=20),
        legend_title="",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(10,15,24,0.72)",
            bordercolor="rgba(255,255,255,0.08)",
            borderwidth=1,
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(10,15,24,0.96)",
            bordercolor="rgba(255,255,255,0.10)",
            font=dict(size=12),
        ),
    )
    fig.update_xaxes(
        showgrid=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
    )
    fig.update_yaxes(
        title=t(lang, "chart_performance_axis"),
        showgrid=True,
        gridcolor="rgba(255,255,255,0.06)",
    )
    return fig


def make_production_equity_chart(
    timeseries_df: pd.DataFrame,
    year: int,
    lang: str,
    main_label: str,
    title: str,
    real_account_exposure_state: dict[str, Any] | None = None,
    model_signal_state: dict[str, Any] | None = None,
    chart_view: str = "model",
) -> go.Figure:
    main_plot = filter_from_year(timeseries_df, year).copy()
    if main_plot.empty:
        raise ValueError("homepage production chart has no rows for the selected year")
    normalized_chart_view = str(chart_view or "model").strip().lower()
    use_real_account_view = normalized_chart_view == "real_account"
    use_live_strategy_view = normalized_chart_view in {"live_strategy", "strategy_execution"}
    if use_real_account_view:
        equity_series = production_chart_real_account_equity_series(main_plot)
        return_series = production_chart_real_account_return_series(main_plot)
        exposure_series = production_chart_real_account_exposure_series(main_plot)
    elif use_live_strategy_view:
        equity_series = production_chart_live_strategy_equity_series(main_plot)
        return_series = production_chart_live_strategy_return_series(main_plot)
        exposure_series = production_chart_live_strategy_exposure_series(main_plot)
    else:
        equity_series = production_chart_authorized_equity_series(main_plot)
        return_series = production_chart_authorized_return_series(main_plot)
        exposure_series = production_chart_authorized_exposure_series(main_plot)
    rebased_equity = rebase_series(equity_series)
    rebased_btc_baseline = rebase_series(production_chart_btc_index_series(main_plot))
    daily_return_pct = return_series * 100.0
    btc_return_pct = production_chart_btc_return_series(main_plot) * 100.0
    btc_close_series = pd.to_numeric(
        main_plot.get("btc_close", pd.Series(index=main_plot.index, dtype="float64")),
        errors="coerce",
    )
    legend_label = main_label
    runtime_model_signal = model_signal_state if isinstance(model_signal_state, dict) else {}
    real_account_label = (
        str(real_account_exposure_state.get("label_sk") or "Reálny účet").strip()
        if isinstance(real_account_exposure_state, dict) and lang == "sk"
        else "Real account"
    )
    model_signal_label = (
        str(runtime_model_signal.get("label_sk") or t(lang, "production_chart_exposure_legend")).strip()
        if lang == "sk"
        else "Model signal"
    )
    legend_label = (
        real_account_label
        if use_real_account_view
        else main_label
        if use_live_strategy_view and str(main_label or "").strip()
        else t(lang, "production_chart_legend")
        if str(t(lang, "production_chart_legend")).strip()
        else main_label
    )
    max_authorized_exposure = max(float(exposure_series.max()) if not exposure_series.empty else 0.0, 1.0)
    fallback_candidate = str(
        first_present_value(
            (real_account_exposure_state or {}).get("asset") if use_real_account_view else None,
            runtime_model_signal.get("preferred_asset"),
            "CASH",
        )
    ).strip().upper()
    candidate_source = (
        pd.Series([fallback_candidate] * len(main_plot), index=main_plot.index)
        if use_real_account_view or use_live_strategy_view
        else main_plot.get(
            "candidate_asset",
            pd.Series([fallback_candidate] * len(main_plot), index=main_plot.index),
        )
    )
    candidate_labels = candidate_source.fillna("").astype(str).map(
        lambda value: product_asset_label_nominative(value, lang)
    )
    trend_permission_values = (
        [abs(float(exposure or 0.0)) > 1e-12 for exposure in exposure_series.tolist()]
        if use_real_account_view or use_live_strategy_view
        else main_plot.get(
            "trend_permission_active",
            pd.Series([abs(float(exposure or 0.0)) > 1e-12 for exposure in exposure_series.tolist()], index=main_plot.index),
        ).tolist()
    )
    market_state_labels = [
        production_market_state_label_from_values(
            exposure=exposure,
            trend_permission_active=trend_permission_active,
            lang=lang,
        )
        for exposure, trend_permission_active in zip(
            exposure_series.tolist(),
            trend_permission_values,
        )
    ]
    real_account_hover_text = ""
    if isinstance(real_account_exposure_state, dict) and real_account_exposure_state.get("is_out_of_market") is True:
        real_asset = str(real_account_exposure_state.get("asset") or "CASH").strip().upper() or "CASH"
        real_state_text = str(real_account_exposure_state.get("state_text") or t(lang, "production_state_out_of_market")).strip()
        real_exposure_text = str(real_account_exposure_state.get("exposure_text") or "0.00x").strip()
        real_account_hover_text = (
            f"{real_account_label}: {real_asset} / {real_state_text} / {real_exposure_text}"
            if lang == "sk"
            else f"{real_account_label}: {real_asset} / {real_state_text} / {real_exposure_text}"
        )

    line_signal_label = real_account_label if use_real_account_view else model_signal_label
    strategy_hover_customdata = list(
        zip(
            [f"{value:+.2f}%" for value in daily_return_pct.tolist()],
            market_state_labels,
            [f"{value:.2f}x" for value in exposure_series.tolist()],
            candidate_labels.tolist(),
            [real_account_hover_text] * len(main_plot),
            [
                (
                    f"{line_signal_label}: {candidate} / {exposure}"
                    if lang == "sk"
                    else f"{line_signal_label}: {candidate} / {exposure}"
                )
                for candidate, exposure in zip(
                    candidate_labels.tolist(),
                    [f"{value:.2f}x" for value in exposure_series.tolist()],
                )
            ],
        )
    )
    btc_hover_customdata = list(
        zip(
            [f"{value:+.2f}%" for value in btc_return_pct.tolist()],
            [
                f"${value:,.2f}" if pd.notna(value) else t(lang, "na")
                for value in btc_close_series.tolist()
            ],
        )
    )
    market_state_flags = [
        state_label == t(lang, "production_hover_market_state_in")
        for state_label in market_state_labels
    ]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.82, 0.18],
    )

    if not main_plot.empty:
        segment_start = pd.Timestamp(main_plot["ts"].iloc[0])
        current_state_flag = market_state_flags[0]
        timestamps = pd.to_datetime(main_plot["ts"], errors="coerce").tolist()
        for idx in range(1, len(main_plot)):
            next_state_flag = market_state_flags[idx]
            if next_state_flag == current_state_flag:
                continue
            segment_end = pd.Timestamp(timestamps[idx])
            fig.add_vrect(
                x0=segment_start,
                x1=segment_end,
                fillcolor="rgba(6,214,160,0.05)" if current_state_flag else "rgba(255,209,102,0.09)",
                opacity=1.0,
                line_width=0,
                layer="below",
                row="all",
                col=1,
            )
            segment_start = segment_end
            current_state_flag = next_state_flag
        fig.add_vrect(
            x0=segment_start,
            x1=pd.Timestamp(timestamps[-1]) + pd.Timedelta(days=1),
            fillcolor="rgba(6,214,160,0.05)" if current_state_flag else "rgba(255,209,102,0.09)",
            opacity=1.0,
            line_width=0,
            layer="below",
            row="all",
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=main_plot["ts"],
            y=rebased_equity,
            mode="lines",
            name=legend_label or main_label,
            line=dict(width=4.8, color="#ff6b6b"),
            customdata=strategy_hover_customdata,
            hovertemplate=(
                f"{t(lang, 'production_hover_date')}: %{{x|%d.%m.%Y}}<br>"
                f"{t(lang, 'production_hover_index')}: %{{y:.2f}}<br>"
                f"{t(lang, 'production_hover_return_net')}: %{{customdata[0]}}<br>"
                f"{t(lang, 'production_hover_market_state')}: %{{customdata[1]}}<br>"
                "%{customdata[5]}<br>"
                "%{customdata[4]}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=main_plot["ts"],
            y=rebased_btc_baseline,
            mode="lines",
            name=t(lang, "production_chart_btc_legend"),
            line=dict(width=2.8, color="#f4b942"),
            customdata=btc_hover_customdata,
            hovertemplate=(
                f"{t(lang, 'production_hover_btc_index')}: %{{y:.2f}}<br>"
                f"{t(lang, 'production_hover_btc_return')}: %{{customdata[0]}}<br>"
                f"{t(lang, 'production_hover_btc_close')}: %{{customdata[1]}}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=main_plot["ts"],
            y=exposure_series,
            mode="lines",
            name=line_signal_label,
            line=dict(width=2.6, color="#06d6a0"),
            line_shape="hv",
            fill="tozeroy",
            fillcolor="rgba(6,214,160,0.20)",
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )

    current_market_state = market_state_labels[-1]
    current_exposure_value = (
        _first_numeric_value(exposure_series.iloc[-1])
        if use_real_account_view or use_live_strategy_view
        else _first_numeric_value(runtime_model_signal.get("exposure_x"), exposure_series.iloc[-1])
    )
    current_exposure_text = f"{float(current_exposure_value or 0.0):.2f}x"
    current_candidate_label = product_asset_label_nominative(
        first_present_value(
            (real_account_exposure_state or {}).get("asset") if use_real_account_view else None,
            runtime_model_signal.get("preferred_asset"),
            candidate_labels.iloc[-1],
        ),
        lang,
    )
    if isinstance(real_account_exposure_state, dict) and real_account_exposure_state.get("is_out_of_market") is True:
        real_asset = str(real_account_exposure_state.get("asset") or "CASH").strip().upper() or "CASH"
        real_exposure_text = str(real_account_exposure_state.get("exposure_text") or "0.00x").strip()
        real_state_text = str(real_account_exposure_state.get("state_text") or t(lang, "production_state_out_of_market")).strip()
        if use_real_account_view:
            annotation_text = f"{real_account_label}: {real_asset} / {real_state_text} / {real_exposure_text}"
        else:
            annotation_text = (
                f"{real_account_label}: {real_asset} / {real_state_text} / {real_exposure_text} | "
                f"{model_signal_label}: {current_candidate_label} / {current_exposure_text}"
                if lang == "sk"
                else f"{real_account_label}: {real_asset} / {real_state_text} / {real_exposure_text} | "
                f"{model_signal_label}: {current_candidate_label} / {current_exposure_text}"
            )
    else:
        annotation_signal_label = line_signal_label if use_real_account_view else model_signal_label
        annotation_text = (
            f"{t(lang, 'production_chart_current_prefix')}: {current_market_state} | "
            f"{annotation_signal_label}: {current_exposure_text} | "
            f"{t(lang, 'production_hover_candidate_asset')}: {current_candidate_label}"
        )

    fig.update_layout(
        height=640,
        title=title,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.015)",
        margin=dict(l=20, r=20, t=70, b=20),
        legend_title="",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(10,15,24,0.72)",
            bordercolor="rgba(255,255,255,0.08)",
            borderwidth=1,
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(10,15,24,0.96)",
            bordercolor="rgba(255,255,255,0.10)",
            font=dict(size=12),
        ),
    )
    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.985,
        showarrow=False,
        text=annotation_text,
        align="left",
        font=dict(size=12, color="#f8fafc"),
        bgcolor="rgba(10,15,24,0.82)",
        bordercolor="rgba(255,255,255,0.10)",
        borderwidth=1,
        borderpad=6,
    )
    fig.update_xaxes(
        showgrid=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        row=1,
        col=1,
    )
    fig.update_xaxes(
        showgrid=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        row=2,
        col=1,
    )
    fig.update_yaxes(
        title=t(lang, "chart_performance_axis"),
        showgrid=True,
        gridcolor="rgba(255,255,255,0.06)",
        row=1,
        col=1,
    )
    fig.update_yaxes(
        title=line_signal_label,
        showgrid=True,
        gridcolor="rgba(255,255,255,0.04)",
        range=[0.0, max_authorized_exposure * 1.1],
        ticksuffix="x",
        row=2,
        col=1,
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.015)",
        margin=dict(l=10, r=10, t=45, b=10),
    )
    return fig


def make_trend_history_chart(history_df: pd.DataFrame, lang: str) -> go.Figure:
    fig = go.Figure()
    default_xaxis_range = None
    if not history_df.empty:
        range_start = pd.Timestamp("2025-01-01")
        latest_trend_ts = pd.to_datetime(history_df["ts"], errors="coerce").max()
        if not pd.isna(latest_trend_ts) and (pd.to_datetime(history_df["ts"], errors="coerce") >= range_start).any():
            default_xaxis_range = [range_start, latest_trend_ts]
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.015)",
        margin=dict(l=20, r=20, t=50, b=20),
        yaxis=dict(range=[-1.05, 1.05], gridcolor="rgba(255,255,255,0.06)"),
        xaxis=dict(showgrid=False, range=default_xaxis_range),
        xaxis_title="",
        legend_title="",
    )
    return fig


# =========================================================
# CONTACT
# =========================================================

def ensure_contact_dir() -> None:
    CONTACT_DIR.mkdir(parents=True, exist_ok=True)


def save_contact_message(email: str, message_type: str, message: str) -> None:
    ensure_contact_dir()

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row_id = uuid.uuid4().hex[:12]

    row = pd.DataFrame(
        [{
            "created_utc": now,
            "id": row_id,
            "email": email.strip(),
            "message_type": message_type.strip(),
            "message": message.strip(),
        }]
    )

    if CONTACT_CSV.exists():
        existing = pd.read_csv(CONTACT_CSV)
        combined = pd.concat([existing, row], ignore_index=True)
    else:
        combined = row

    combined.to_csv(CONTACT_CSV, index=False)


# =========================================================
# ACCOUNT AUTH
# =========================================================

def load_account_login_credentials() -> tuple[str, str, str]:
    try:
        account_login = st.secrets.get("account_login", {})
    except Exception:
        account_login = {}

    if hasattr(account_login, "get"):
        username = str(account_login.get("username") or "").strip()
        password = str(account_login.get("password") or "").strip()
        if username and password:
            return username, password, "secrets"

    username = str(os.getenv("ACCOUNT_TAB_USERNAME") or "").strip()
    password = str(os.getenv("ACCOUNT_TAB_PASSWORD") or "").strip()
    if username and password:
        return username, password, "env"

    return "", "", ""


# =========================================================
# APP
# =========================================================

inject_css()

if "lang" not in st.session_state:
    st.session_state.lang = "sk"
if "execution_bridge_result" not in st.session_state:
    st.session_state.execution_bridge_result = {}
if "account_authenticated" not in st.session_state:
    st.session_state.account_authenticated = False
if "account_auth_error" not in st.session_state:
    st.session_state.account_auth_error = ""

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
    btc_indicator_slot = st.empty()

st.session_state.lang = "sk" if lang_choice == "SK" else "en"
lang = st.session_state.lang

latest_successful_snapshot_payload = load_required_authority_payload(
    AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
)
latest_attempt_status_payload = load_optional_authority_payload(
    AUTHORITY_LATEST_ATTEMPT_STATUS_PATH,
    ATTEMPT_STATUS_ARTIFACT_TYPE,
)
product_snapshot = require_snapshot_payload(
    dict(latest_successful_snapshot_payload.get("app_product_snapshot") or {}),
    "app_product_snapshot",
    AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH,
)
data_health_report = build_live_data_health_report()
data_health_status_model = build_homepage_data_health_status_model(
    data_health_report,
    latest_successful_snapshot_payload,
    latest_attempt_status_payload,
)
render_data_health_banner(
    data_health_report,
    data_health_status_model,
    lang,
    latest_successful_snapshot_payload,
)
runtime_authority_payload, runtime_snapshot_source_path, _runtime_authority_source_type = (
    select_preferred_authority_payload(
        latest_successful_snapshot_payload,
        latest_attempt_status_payload,
    )
)
runtime_snapshot = load_runtime_snapshot_for_app(
    dict(runtime_authority_payload.get("app_runtime_snapshot") or {}),
    runtime_snapshot_source_path,
)
selector_cfg = build_selector_config_from_snapshot(product_snapshot, runtime_snapshot)

with hero_left:
    st.markdown('<div class="hero-wrap">', unsafe_allow_html=True)
    st.title(selector_cfg.get("product_name") or "TrendAtlas Crypto")
    st.markdown('<div class="gradient-line"></div>', unsafe_allow_html=True)
    st.markdown(f"## {t(lang, 'hero')}")
    st.caption(t(lang, "subhero"))
    st.markdown("</div>", unsafe_allow_html=True)

production_bundle = load_production_homepage_bundle()
production_snapshot = dict(production_bundle["snapshot"])
production_diagnostics = dict(production_bundle["diagnostics"])
production_quality = dict(production_bundle["quality"])
production_timeseries_df = production_bundle["timeseries"].copy()

main_key = str(production_snapshot.get("strategy_version") or "").strip()
labels = build_display_map(selector_cfg, lang)
labels[main_key] = main_key
btc_side_indicator = build_btc_side_indicator_data()
with btc_indicator_slot.container():
    render_btc_side_indicator(btc_side_indicator)

trend_live = build_production_trend_live(production_snapshot, production_timeseries_df)
trend_history_df = build_production_trend_history(production_timeseries_df)
trend_barometer_warnings: list[str] = []
if trend_live.get("trend_state_label"):
    trend_live["trend_state_label"] = prettify_trend_state(trend_live.get("trend_state_label"), lang)
account_observability_cfg = get_current_account_observability_contract(selector_cfg)
account_runtime_snapshot = select_preferred_account_runtime_snapshot(runtime_snapshot)
account_status_payload = dict(account_runtime_snapshot.get("execution_status") or {})
account_snapshot_payload = dict(account_runtime_snapshot.get("account_snapshot_summary") or {})
account_snapshot_view = dict(account_snapshot_payload)
dashboard_public_status = load_dashboard_public_status_for_app(
    account_runtime_snapshot,
    production_snapshot,
)
dashboard_public_state = resolve_dashboard_public_status_state(
    dashboard_public_status,
    lang,
)
dashboard_public_chart_timeseries_df = load_dashboard_public_chart_timeseries_frame(
    LOCAL_DASHBOARD_PUBLIC_CHART_TIMESERIES_PATH
)
runtime_real_account_state = dict(runtime_snapshot.get("real_account_state") or {})
runtime_model_signal_state = dict(
    dashboard_public_state.get("model_signal_state")
    or runtime_snapshot.get("model_signal_state")
    or {}
)
runtime_model_performance_state = dict(
    dashboard_public_state.get("model_performance_state")
    or runtime_snapshot.get("model_performance_state")
    or {}
)
dashboard_public_labels_sk = dict(dashboard_public_state.get("public_labels_sk") or {})
runtime_health_payload = dict(runtime_snapshot.get("runtime_health_summary") or {})
dry_run_decision_payload = dict(runtime_snapshot.get("dry_run_summary") or {})
real_order_gate_payload = dict(runtime_snapshot.get("gate_summary") or {})
execution_mode_payload = dict(runtime_snapshot.get("execution_mode_posture") or {})
live_order_policy_payload = dict(runtime_snapshot.get("live_order_policy_summary") or {})
trading_operation_mode_payload = dict(execution_mode_payload.get("trading_operation_mode") or {})
runtime_last_sync_utc = runtime_snapshot.get("runtime_last_sync_utc")
account_snapshot_as_of_utc = account_runtime_snapshot.get("account_snapshot_as_of_utc")
dry_run_generated_at_utc = runtime_snapshot.get("dry_run_generated_at_utc")
gate_generated_at_utc = runtime_snapshot.get("gate_generated_at_utc")
runtime_table_payload = build_authority_runtime_table_snapshot(
    latest_successful_snapshot_payload,
    latest_attempt_status_payload,
)
runtime_guardrail_payload = get_nested_dict(runtime_health_payload, "execution_mode_guardrail")

main_metrics = resolve_main_metrics_for_display(
    dict(production_snapshot.get("metrics") or {}),
    main_key,
)
public_performance_context = build_public_homepage_performance_context(
    production_snapshot,
    production_timeseries_df,
)
public_performance_timeseries_df = public_performance_context["timeseries_df"]
main_metrics = dict(public_performance_context["main_metrics"])
top_performance_metrics = dict(public_performance_context["top_performance_metrics"])

years = available_years_from_frames([dashboard_public_chart_timeseries_df])
if not years:
    st.error(f"{t(lang, 'load_failed')}: no usable dates")
    st.stop()

main_equity_df = (
    dashboard_public_chart_timeseries_df[["ts", "model_index"]]
    .rename(columns={"model_index": "equity"})
    .dropna()
    .copy()
)

tabs = st.tabs(t(lang, "tabs"))

with tabs[0]:
    trade_count_label = t(lang, "trade_count")
    current_drawdown_label = t(lang, "current_drawdown")
    real_account_exposure_state = dict(
        dashboard_public_state.get("real_account_exposure_state") or {}
    )
    if not real_account_exposure_state:
        real_account_exposure_state = resolve_real_account_exposure_state(
            account_snapshot_view=account_snapshot_view,
            dry_run_decision_payload=dry_run_decision_payload,
            real_order_gate_payload=real_order_gate_payload,
            production_snapshot=production_snapshot,
            lang=lang,
            runtime_real_account_state=runtime_real_account_state,
        )
    strategy_signal_exposure = _first_numeric_value(
        runtime_model_signal_state.get("exposure_x"),
    )
    strategy_signal_exposure_text = (
        f"{strategy_signal_exposure:.2f}x"
        if strategy_signal_exposure is not None
        else t(lang, "na")
    )
    state_story = build_homepage_state_story(
        production_snapshot,
        production_diagnostics,
        lang,
        real_account_exposure_state,
        runtime_model_signal_state,
    )
    wait_condition = dict(production_diagnostics.get("current_wait_condition") or {})
    current_trade_state = dict(production_diagnostics.get("current_trade_state") or {})
    recent_rebalance_rows = [
        {
            "Date" if lang == "en" else "Datum": format_date_text(item.get("date"), lang),
            "Asset" if lang == "en" else "Stav": product_asset_label_nominative(item.get("held_asset"), lang),
            "Exposure" if lang == "en" else "Expozicia": safe_text_value(item.get("exposure"), lang=lang),
            "Reason" if lang == "en" else "Dovod": _sk_reason_code_label(str(item.get("reason_code") or "").strip().lower()) if lang == "sk" else safe_text_value(item.get("reason_text"), lang=lang),
        }
        for item in list(production_diagnostics.get("recent_rebalance_events") or [])[:5]
    ]
    recent_regime_rows = [
        {
            "Date" if lang == "en" else "Datum": format_date_text(item.get("date"), lang),
            "Asset" if lang == "en" else "Stav": product_asset_label_nominative(item.get("held_asset"), lang),
            "Regime" if lang == "en" else "Rezim": product_asset_label_nominative(item.get("regime"), lang),
            "Reason" if lang == "en" else "Dovod": _sk_reason_code_label(str(item.get("reason_code") or "").strip().lower()) if lang == "sk" else safe_text_value(item.get("reason_code"), lang=lang),
        }
        for item in list(production_diagnostics.get("recent_regime_changes") or [])[:5]
    ]
    real_account_card_label = (
        str(
            real_account_exposure_state.get("label_sk")
            or dashboard_public_labels_sk.get("real_account")
            or "Reálny účet"
        ).strip()
        if lang == "sk"
        else t(lang, "production_market_exposure")
    )
    model_signal_card_label = (
        str(
            runtime_model_signal_state.get("label_sk")
            or dashboard_public_labels_sk.get("model_signal")
            or "Modelový signál"
        ).strip()
        if lang == "sk"
        else t(lang, "production_exposure")
    )

    home_cards = [
        {
            "label": real_account_card_label,
            "value": real_account_exposure_state["value"],
            "subtitle": real_account_exposure_state["subtitle"],
            "help": METRIC_HELP[lang][t(lang, "production_market_exposure")],
            "accent": "blue",
        },
        {
            "label": t(lang, "production_candidate_asset"),
            "value": product_asset_label_nominative(
                runtime_model_signal_state.get("preferred_asset"),
                lang,
            ),
            "subtitle": t(lang, "production_candidate_hint"),
            "help": METRIC_HELP[lang][t(lang, "production_candidate_asset")],
            "accent": "green",
        },
        {
            "label": model_signal_card_label,
            "value": strategy_signal_exposure_text,
            "subtitle": (
                "Signal modelu, nie expozicia uctu"
                if lang == "sk" and runtime_model_signal_state.get("not_real_wallet_exposure") is not False
                else "Model signal, not account exposure"
                if runtime_model_signal_state.get("not_real_wallet_exposure") is not False
                else ""
            ),
            "help": METRIC_HELP[lang][t(lang, "production_exposure")],
            "accent": "orange",
        },
        {
            "label": t(lang, "production_closed_day"),
            "value": format_date_text(production_snapshot.get("closed_day"), lang),
            "subtitle": (
                f"{t(lang, 'production_next_rebalance')}: "
                f"{format_date_text(production_snapshot.get('next_rebalance_date'), lang)}"
            ),
            "help": METRIC_HELP[lang][t(lang, "production_closed_day")],
            "accent": "violet",
        },
    ]
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

    model_chart_title = (
        str(runtime_model_performance_state.get("label_sk") or "").strip()
        if lang == "sk"
        else t(lang, "chart_title")
    ) or t(lang, "chart_title")
    st.markdown(f"### {model_chart_title}")
    selected_year_home = st.selectbox(
        t(lang, "chart_year"),
        options=years,
        index=years.index(2025) if 2025 in years else 0,
        key="selected_year_home",
    )
    st.plotly_chart(
        make_production_equity_chart(
            timeseries_df=dashboard_public_chart_timeseries_df,
            year=selected_year_home,
            lang=lang,
            main_label=t(lang, "production_chart_legend"),
            title=model_chart_title,
            real_account_exposure_state=real_account_exposure_state,
            model_signal_state=runtime_model_signal_state,
            chart_view="model",
        ),
        width="stretch",
    )
    st.caption(
        build_production_chart_current_state_note(
            production_snapshot,
            production_diagnostics,
            lang,
            real_account_exposure_state,
            runtime_model_signal_state,
        )
    )
    st.caption(t(lang, "production_chart_note"))
    st.caption(t(lang, "production_chart_baseline_note"))
    st.caption(t(lang, "production_chart_flat_note"))
    st.caption(t(lang, "production_chart_participation_note"))
    st.markdown(f"### {t(lang, 'performance_title')}")
    st.caption(t(lang, "performance_fee_note"))
    public_window_label_key = str(public_performance_context.get("public_window_label_key") or "since2023")
    public_window_metric_key = str(public_performance_context.get("public_window_metric_key") or "since2023_cagr_pct")
    public_window_label = t(lang, public_window_label_key)
    public_average_annual_growth_pct = first_present_value(
        runtime_model_performance_state.get("public_average_annual_growth_pct"),
        top_performance_metrics.get("cagr_pct"),
    )
    since_etf_start_cagr_pct = first_present_value(
        runtime_model_performance_state.get("since_etf_start_cagr_pct"),
        top_performance_metrics.get(public_window_metric_key),
    )
    since2025_cagr_pct = first_present_value(
        runtime_model_performance_state.get("since2025_cagr_pct"),
        top_performance_metrics.get("since2025_cagr_pct"),
    )
    perf1 = st.columns(4)
    with perf1[0]:
        render_color_card(t(lang, "cagr"), safe_metric_text(public_average_annual_growth_pct, lang=lang), "", METRIC_HELP[lang][t(lang, "cagr")], "blue")
    with perf1[1]:
        render_color_card(public_window_label, safe_metric_text(since_etf_start_cagr_pct, lang=lang), "CAGR", METRIC_HELP[lang][public_window_label], "green")
    with perf1[2]:
        render_color_card(t(lang, "since2025"), safe_metric_text(since2025_cagr_pct, lang=lang), "CAGR", METRIC_HELP[lang][t(lang, "since2025")], "violet")
    with perf1[3]:
        render_color_card(t(lang, "total_return"), safe_metric_text(main_metrics.get("total_return_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "total_return")], "neutral")

    perf2 = st.columns(4)
    with perf2[0]:
        render_color_card(t(lang, "sharpe"), safe_plain_number_text(main_metrics.get("sharpe"), lang=lang), "", METRIC_HELP[lang][t(lang, "sharpe")], "blue")
    with perf2[1]:
        render_color_card(t(lang, "sortino"), safe_plain_number_text(main_metrics.get("sortino"), lang=lang), "", METRIC_HELP[lang][t(lang, "sortino")], "green")
    with perf2[2]:
        render_color_card(t(lang, "max_dd"), safe_metric_text(main_metrics.get("max_drawdown_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "max_dd")], "orange")
    with perf2[3]:
        render_color_card(
            trade_count_label,
            safe_int_text(main_metrics.get("trade_count"), lang=lang),
            "",
            METRIC_HELP[lang].get(trade_count_label),
            "neutral",
        )

    st.markdown(f"### {t(lang, 'trend_title')}")
    st.caption(t(lang, "trend_desc"))

    if trend_barometer_warnings:
        for warning_text in trend_barometer_warnings:
            st.warning(warning_text)
    trend_cols = st.columns([1.35, 1.65])
    with trend_cols[0]:
        st.plotly_chart(make_trend_gauge(trend_live, lang), width="stretch")

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
            st.caption(
                f"{'Datum vypoctu' if lang == 'sk' else 'Calc date'}: "
                f"{format_date_text(trend_live.get('trend_calc_date'), lang)}"
            )

    if not trend_history_df.empty:
        st.plotly_chart(make_trend_history_chart(trend_history_df, lang), width="stretch")
        st.caption(t(lang, "trend_history_note"))

    st.markdown(f"### {t(lang, 'ops_title')}")
    ops = st.columns(4)
    with ops[0]:
        render_color_card(t(lang, "switch_count"), safe_int_text(main_metrics.get("switch_count"), lang=lang), "", METRIC_HELP[lang][t(lang, "switch_count")], "blue")
    with ops[1]:
        render_color_card(t(lang, "cash_days"), safe_day_metric_text(main_metrics.get("cash_days_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "cash_days")], "neutral")
    with ops[2]:
        render_color_card(t(lang, "btc_days"), safe_day_metric_text(main_metrics.get("btc_days_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "btc_days")], "green")
    with ops[3]:
        render_color_card(
            current_drawdown_label,
            safe_metric_text(get_nested_value(production_snapshot, "decision_context", "current_drawdown_pct"), lang=lang),
            "",
            METRIC_HELP[lang].get(current_drawdown_label),
            "violet",
        )

    st.markdown(f"### {t(lang, 'production_reason_title')}")
    validation_label = (
        t(lang, "production_validation_passed")
        if str(production_quality.get("status") or "").strip().lower() == "passed"
        else t(lang, "production_validation_failed")
    )
    render_ops_inline_note(
        t(lang, "production_signal_health"),
        f"{validation_label}. {t(lang, 'production_data_source_note')}",
    )
    story_top = st.columns(2)
    with story_top[0]:
        render_story_panel(
            t(lang, "production_status_now"),
            state_story["now"],
            eyebrow=t(lang, "production_market_state"),
            tone="cool",
        )
    with story_top[1]:
        render_story_panel(
            t(lang, "production_status_why"),
            state_story["why"],
            eyebrow=t(lang, "production_reason_title"),
            tone="proof",
        )

    story_bottom = st.columns(2)
    with story_bottom[0]:
        render_story_panel(
            t(lang, "production_wait_title"),
            state_story["wait"],
            eyebrow=f"{t(lang, 'production_waiting_label')}: {t(lang, 'production_waiting_yes') if as_bool(current_trade_state.get('is_waiting')) else t(lang, 'production_waiting_no')}",
            tone="warm",
        )
    with story_bottom[1]:
        render_story_panel(
            t(lang, "production_status_change"),
            state_story["change"],
            eyebrow=t(lang, "production_wait_target"),
            tone="alert",
        )

    render_story_list_panel(
        t(lang, "production_status_risks"),
        state_story["risks"],
        eyebrow=t(lang, "production_pain_title"),
        tone="warm",
    )

    if recent_rebalance_rows:
        with st.expander(t(lang, "production_recent_rebalances"), expanded=False):
            render_app_table(recent_rebalance_rows, emphasize_first_column=True)
    if recent_regime_rows:
        with st.expander(t(lang, "production_recent_regimes"), expanded=False):
            render_app_table(recent_regime_rows, emphasize_first_column=True)

    refresh_currentness_state = str(
        runtime_table_payload.get("currentness_state") or "missing_authority_artifact"
    ).strip()
    refresh_currentness_reason = str(
        runtime_table_payload.get("currentness_reason")
        or FRESHNESS_SUMMARY_TEXT.get(refresh_currentness_state, FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"])
    ).strip()
    refresh_currentness_state_public = {
        "current": "Aktualne" if lang == "sk" else "Current",
        "stale": "Zastarane" if lang == "sk" else "Stale",
        "refresh_in_progress": "Prebieha aktualizacia" if lang == "sk" else "Refresh in progress",
        "refresh_failed": "Aktualizacia zlyhala" if lang == "sk" else "Refresh failed",
        "missing_authority_artifact": "Stav nie je dostupny" if lang == "sk" else "Status unavailable",
    }.get(refresh_currentness_state, "Nedostupne" if lang == "sk" else "Unavailable")
    pi_runtime_update_utc = runtime_table_payload.get("last_pi_update_utc")
    wallet_sync_utc = runtime_table_payload.get("last_wallet_sync_utc")
    refresh_label_column = "Preh\u013ead" if lang == "sk" else "Field"
    refresh_value_column = "Hodnota" if lang == "sk" else "Value"
    refresh_rows = [
        {
            refresh_label_column: "Posledna aktualizacia" if lang == "sk" else "Latest update",
            refresh_value_column: format_local_time_text(
                pi_runtime_update_utc,
                lang,
            ),
        },
        {
            refresh_label_column: "Stav poslednej aktualizacie" if lang == "sk" else "Latest update status",
            refresh_value_column: safe_text_value(
                runtime_table_payload.get("last_refresh_status"),
                lang=lang,
            ),
        },
        {
            refresh_label_column: "Referencne cislo aktualizacie" if lang == "sk" else "Update reference",
            refresh_value_column: safe_text_value(
                runtime_table_payload.get("last_refresh_run_id"),
                lang=lang,
            ),
        },
        {
            refresh_label_column: "Posledn\u00e1 synchroniz\u00e1cia pe\u0148a\u017eenky" if lang == "sk" else "Last wallet sync",
            refresh_value_column: format_local_time_text(
                wallet_sync_utc,
                lang,
            ),
        },
        {
            refresh_label_column: "Aktualnost dat" if lang == "sk" else "Data currentness",
            refresh_value_column: refresh_currentness_state_public,
        },
        {
            refresh_label_column: "D\u00f4vod stavu" if lang == "sk" else "Reason",
            refresh_value_column: safe_text_value(
                refresh_currentness_reason,
                lang=lang,
            ),
        },
    ]
    render_data_health_details(data_health_report, data_health_status_model, lang, refresh_rows)

    st.markdown(f"### {t(lang, 'overview_title')}")
    st.markdown(t(lang, "overview_md"))

with tabs[1]:
    configured_account_username, configured_account_password, _account_login_source = load_account_login_credentials()
    account_login_available = bool(configured_account_username and configured_account_password)
    if not account_login_available:
        st.session_state.account_authenticated = False

    title_col, action_col = st.columns([6, 1])
    with title_col:
        st.subheader(t(lang, "account_title"))
    with action_col:
        if account_login_available and st.session_state.account_authenticated:
            if st.button("Odhlásiť", key="account_logout", width="stretch"):
                st.session_state.account_authenticated = False
                st.session_state.account_auth_error = ""
                st.rerun()

    account_enabled_cfg = as_bool(account_observability_cfg.get("enabled"))
    account_enabled = account_enabled_cfg if account_login_available and st.session_state.account_authenticated else False

    if not account_login_available:
        st.warning("Prístup k účtu je dočasne nedostupný.")
    elif not st.session_state.account_authenticated:
        st.markdown("#### Prihlásenie")
        st.info("Pre prístup k účtu sa najprv prihláste.")
        with st.form("account_login_form", clear_on_submit=True):
            username_input = st.text_input("Používateľské meno")
            password_input = st.text_input("Heslo", type="password")
            login_submitted = st.form_submit_button("Prihlásiť sa", width="stretch")

        if login_submitted:
            username_ok = hmac.compare_digest(username_input.strip(), configured_account_username)
            password_ok = hmac.compare_digest(password_input, configured_account_password)
            if username_ok and password_ok:
                st.session_state.account_authenticated = True
                st.session_state.account_auth_error = ""
                st.rerun()
            st.session_state.account_authenticated = False
            st.session_state.account_auth_error = "Nesprávne prihlasovacie údaje."

        if st.session_state.account_auth_error:
            st.error(st.session_state.account_auth_error)
    else:
        st.caption(t(lang, "account_snapshot_note"))

    if account_enabled is False:
        if account_login_available and st.session_state.account_authenticated and account_enabled_cfg is False:
            st.info(account_ui_text(lang, "observability_disabled"))
    else:
        bridge_available = callable(run_app_execute_action)

        refresh_missing_artifacts = []
        if not account_status_payload:
            refresh_missing_artifacts.append("execution_status.json")
        if not account_snapshot_payload:
            refresh_missing_artifacts.append("hyperliquid_account_snapshot.json")

        refresh_trading_enabled_value = first_present_value(
            runtime_guardrail_payload.get("trading_enabled"),
            account_status_payload.get("trading_enabled"),
            account_snapshot_payload.get("trading_enabled"),
            False if (account_status_payload or account_snapshot_payload) else None,
        )
        refresh_kill_switch_value = first_present_value(
            runtime_guardrail_payload.get("kill_switch"),
            account_status_payload.get("kill_switch"),
            account_snapshot_payload.get("kill_switch"),
            True if runtime_guardrail_payload else None,
        )

        dry_run_missing_artifacts = []
        if not dry_run_decision_payload:
            dry_run_missing_artifacts.append("latest_dry_run_decision.json")

        live_gate_state = build_live_execute_gate_state(
            bridge_available=bridge_available,
            bridge_import_error=APP_EXECUTE_BRIDGE_IMPORT_ERROR,
            execution_mode_payload=execution_mode_payload,
            live_order_policy_payload=live_order_policy_payload,
            dry_run_decision_payload=dry_run_decision_payload,
            real_order_gate_payload=real_order_gate_payload,
        )
        operation_mode = str(trading_operation_mode_payload.get("mode") or "").strip().lower()
        operation_mode_label = (
            "Zapnutá"
            if lang == "sk" and operation_mode == "automatic"
            else "Vypnutá"
            if lang == "sk"
            else "Enabled"
            if operation_mode == "automatic"
            else "Disabled"
        )

        if refresh_missing_artifacts:
            refresh_missing_artifacts = [
                "Niektore udaje momentalne chybaju."
                if lang == "sk"
                else "Some account inputs are currently missing."
            ]
        if dry_run_missing_artifacts:
            dry_run_missing_artifacts = [
                "Niektore podklady pre skusobne vyhodnotenie momentalne chybaju."
                if lang == "sk"
                else "Some dry-run inputs are currently missing."
            ]

        live_trading_enabled_value = first_present_value(
            execution_mode_payload.get("trading_enabled"),
            get_nested_value(real_order_gate_payload, "checks", "execution_trading_enabled"),
        )
        live_kill_switch_value = first_present_value(
            execution_mode_payload.get("kill_switch"),
            get_nested_value(real_order_gate_payload, "checks", "kill_switch"),
        )

        refresh_stop_reason = str(runtime_health_payload.get("stop_reason") or "").strip()
        dry_run_stop_reason = refresh_stop_reason
        live_stop_reason = str(real_order_gate_payload.get("status") or "").strip()
        refresh_timestamp = format_local_time_text(account_snapshot_as_of_utc, lang)
        dry_run_timestamp = format_local_time_text(dry_run_generated_at_utc, lang)
        dry_run_recommended_action = str(dry_run_decision_payload.get("recommended_action") or "").strip().lower()
        if lang == "sk" and dry_run_recommended_action == "hold_cash":
            dry_run_summary_text = "Dnes systém nevidí obchod, ktorý by mal odoslať."
        else:
            dry_run_summary_text = (
                f"Odporucana akcia {pretty_token(dry_run_decision_payload.get('recommended_action'), lang)} | "
                f"Cielovy asset {safe_text_value(dry_run_decision_payload.get('target_asset'), lang=lang)}"
            )

        open_position = account_snapshot_view.get("open_position")
        connection_text = prettify_account_status(account_snapshot_view.get("status"), lang)
        last_action_text = prettify_account_action(account_snapshot_view.get("last_action"), lang)
        last_result_text = prettify_account_result(account_snapshot_view.get("last_action_result"), lang)
        runtime_error_text = safe_text_value(account_snapshot_view.get("error"), lang=lang)
        no_position = not isinstance(open_position, dict)
        open_position_subtitle = ""
        sync_text = format_local_time_text(account_snapshot_as_of_utc, lang)
        account_status_text = connection_text if account_snapshot_view.get("status") else t(lang, "account_status_unavailable")
        proof_state_text = "Udaje su informativne" if lang == "sk" else "Informational only"
        placeholder_framing = (
            "Nejde o oficialne potvrdenie live obchodovania."
            if lang == "sk"
            else "This is not official proof of live trading."
        )
        read_mode_text = prettify_account_read_mode(account_observability_cfg.get("read_mode"), lang)
        mode_text = pretty_token(account_snapshot_view.get("mode"), lang)
        provider_text = safe_text_value(account_snapshot_view.get("provider"), lang=lang)
        full_account_address = str(account_snapshot_view.get("account_address") or "").strip()
        if len(full_account_address) >= 12:
            masked_account_address = f"{full_account_address[:6]}...{full_account_address[-4:]}"
        else:
            masked_account_address = safe_text_value(full_account_address, lang=lang)
        balance_source_text = prettify_balance_source(account_snapshot_view.get("balance_source_of_truth"), lang)

        if not no_position:
            side_key = str(open_position.get("side")).upper()
            if side_key == "LONG":
                side_text = t(lang, "account_long")
            elif side_key == "SHORT":
                side_text = t(lang, "account_short")
            else:
                side_text = safe_text_value(open_position.get("side"), lang=lang)
            open_position_subtitle = f"{side_text} | {safe_plain_number_text(open_position.get('size'), decimals=6, lang=lang)}"

        if runtime_error_text != t(lang, "na"):
            friendly_runtime_error = friendly_hyperliquid_error_message(runtime_error_text, lang)
            st.warning(friendly_runtime_error or f"{account_ui_text(lang, 'runtime_error')}: {runtime_error_text}")

        execution_notice = build_execution_notice(st.session_state.execution_bridge_result, lang)
        if execution_notice:
            execution_notice_status = str(
                (st.session_state.execution_bridge_result or {}).get("status") or ""
            ).strip().lower()
            if execution_notice_status in {"failed", "blocked"}:
                st.error(execution_notice)
            else:
                st.info(execution_notice)

        st.markdown("#### Stav a ovládanie")
        with st.container(border=True):
            render_ops_strip(
                [
                    {
                        "label": "Automaticke obchody" if lang == "sk" else "Automatic trading",
                        "value": operation_mode_label,
                    },
                    {
                        "label": "Realny ucet" if lang == "sk" else "Real account",
                        "value": str(real_account_exposure_state.get("state_text") or t(lang, "production_state_out_of_market")),
                    },
                    {
                        "label": "Asset uctu" if lang == "sk" else "Account asset",
                        "value": str(real_account_exposure_state.get("asset") or "CASH"),
                    },
                    {
                        "label": "Realna expozicia" if lang == "sk" else "Real exposure",
                        "value": str(real_account_exposure_state.get("exposure_text") or "0.00x"),
                    },
                    {
                        "label": "Odoslanie obchodu" if lang == "sk" else "Order placement",
                        "value": (
                            "Blokovane"
                            if lang == "sk" and (
                                real_account_exposure_state.get("gate_status") == "blocked"
                                or real_account_exposure_state.get("would_place_real_order") is False
                            )
                            else "Blocked"
                            if (
                                real_account_exposure_state.get("gate_status") == "blocked"
                                or real_account_exposure_state.get("would_place_real_order") is False
                            )
                            else "Povolene"
                            if lang == "sk"
                            else "Allowed"
                        ),
                    },
                ],
                tone="control",
            )

            toggle_col, refresh_col = st.columns(2)
            toggle_is_automatic = operation_mode == "automatic"
            toggle_label = (
                "Vypnúť automatické obchody"
                if toggle_is_automatic and lang == "sk"
                else "Zapnúť automatické obchody"
                if lang == "sk"
                else "Disable automatic trading"
                if toggle_is_automatic
                else "Enable automatic trading"
            )
            toggle_action = "set_manual_mode" if toggle_is_automatic else "set_automatic_mode"

            with toggle_col:
                if st.button(
                    toggle_label,
                    key="execution_controls_toggle_automatic_mode",
                    width="stretch",
                    disabled=not bridge_available,
                ):
                    result = run_app_execute_action(action=toggle_action)
                    st.session_state.execution_bridge_result = result
                    st.rerun()

            with refresh_col:
                if st.button(
                    "Obnoviť údaje z peňaženky" if lang == "sk" else "Refresh wallet data",
                    key="execution_controls_refresh",
                    width="stretch",
                    disabled=not bridge_available,
                ):
                    with st.spinner("Obnovujem údaje z peňaženky..." if lang == "sk" else "Refreshing wallet data..."):
                        result = run_app_execute_action(action="refresh")
                    st.session_state.execution_bridge_result = result
                    st.rerun()

        st.markdown(f"#### {account_ui_text(lang, 'overview')}")
        render_ops_strip(
            [
                {
                    "label": t(lang, "account_connection"),
                    "value": connection_text if account_snapshot_view.get("status") else t(lang, "account_status_unavailable"),
                },
                {
                    "label": t(lang, "account_last_sync"),
                    "value": format_local_time_text(account_snapshot_as_of_utc, lang),
                },
                {
                    "label": t(lang, "account_provider"),
                    "value": provider_text,
                },
                {
                    "label": account_ui_text(lang, "mode"),
                    "value": mode_text,
                },
            ],
            tone="overview",
        )
        render_ops_inline_note(t(lang, "account_address"), masked_account_address)

        st.markdown(f"#### {account_ui_text(lang, 'balances')}")
        render_ops_kpi_row(
            [
                {
                    "label": t(lang, "account_total_value"),
                    "value": safe_usd_text(account_snapshot_view.get("account_equity_usd"), lang=lang),
                    "subtitle": "Primarny KPI",
                },
                {
                    "label": t(lang, "account_available_balance"),
                    "value": safe_usd_text(account_snapshot_view.get("available_balance_usd"), lang=lang),
                    "subtitle": "Likvidna cast uctu",
                },
                {
                    "label": "Zdroj zostatku" if lang == "sk" else "Balance source",
                    "value": balance_source_text,
                    "subtitle": "Operativny zdroj hodnoty",
                },
            ],
            tone="balance",
        )

        dense_cols = st.columns(2, gap="large")
        with dense_cols[0]:
            render_ops_dense_panel(
                account_ui_text(lang, "positions"),
                [
                    {
                        "label": t(lang, "account_open_position"),
                        "value": safe_text_value(open_position.get("symbol"), lang=lang) if not no_position else t(lang, "account_no_position"),
                        "subtitle": open_position_subtitle,
                    },
                    {
                        "label": "Pocet pozicii" if lang == "sk" else "Positions count",
                        "value": safe_int_text(account_snapshot_view.get("positions_count"), lang=lang),
                    },
                    {
                        "label": t(lang, "account_open_orders"),
                        "value": safe_int_text(account_snapshot_view.get("open_orders_count"), lang=lang),
                    },
                ],
                tone="position",
            )
        with dense_cols[1]:
            render_ops_dense_panel(
                account_ui_text(lang, "activity"),
                [
                    {
                        "label": t(lang, "account_recent_fills"),
                        "value": safe_int_text(account_snapshot_view.get("recent_fills_count"), lang=lang),
                    },
                    {
                        "label": t(lang, "account_last_action"),
                        "value": last_action_text,
                    },
                    {
                        "label": t(lang, "account_last_result"),
                        "value": last_result_text,
                    },
                ],
                tone="activity",
            )

with tabs[2]:
    st.subheader(t(lang, "method_title"))
    st.markdown(t(lang, "method_md"))

with tabs[3]:
    st.subheader(t(lang, "contact_title"))
    st.caption(t(lang, "contact_desc"))

    with st.form("contact_form", clear_on_submit=True):
        email = st.text_input(t(lang, "contact_email"))
        message_type = st.selectbox(t(lang, "contact_type"), options=t(lang, "contact_type_options"))
        message = st.text_area(
            t(lang, "contact_message"),
            placeholder=t(lang, "contact_placeholder"),
            height=180,
        )
        honeypot = st.text_input("website", value="", help="Leave blank", label_visibility="collapsed")
        submitted = st.form_submit_button(t(lang, "contact_send"))

    if submitted:
        if honeypot.strip():
            st.success(t(lang, "contact_saved"))
        elif not email.strip() or not message.strip():
            st.warning(t(lang, "contact_need_input"))
        elif not valid_email(email):
            st.warning(t(lang, "contact_bad_email"))
        else:
            try:
                save_contact_message(email=email, message_type=message_type, message=message)
                st.success(t(lang, "contact_saved"))
            except Exception as e:
                st.error(f"{t(lang, 'contact_failed')}: {e}")

    st.caption(t(lang, "contact_files"))




