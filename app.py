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
import streamlit as st
from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
)
from scripts.execution.trading_operation_mode import (
    DEFAULT_TRADING_OPERATION_MODE_PATH,
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
PRODUCTION_SNAPSHOT_PATH = PRODUCTION_OUTPUTS / "current_strategy_snapshot.json"
PRODUCTION_TIMESERIES_PATH = PRODUCTION_OUTPUTS / "current_strategy_timeseries.csv"
PRODUCTION_DIAGNOSTICS_PATH = PRODUCTION_OUTPUTS / "current_strategy_diagnostics.json"
PRODUCTION_QUALITY_PATH = PRODUCTION_OUTPUTS / "current_strategy_snapshot.quality.json"
TRADING_OPERATION_MODE_CONFIG_PATH = DEFAULT_TRADING_OPERATION_MODE_PATH
LIVE_ORDER_CONFIRMATION_TEXT = "POTVRDZUJEM"
APP_DISPLAY_TIMEZONE = ZoneInfo("Europe/Bratislava")
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
        "chart_state_base": "BASE",
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
Znamená to, že podľa interných pravidiel ešte trh neprekročil kvalitatívnu hranicu pre nákup, alebo žiadny kandidát nie je dosť presvedčivý na reálnu expozíciu.

Aj preto môže systém interne vidieť lídra, ale obchod ešte nespustiť.  
Kandidát môže existovať, no bezpečnostná a riadiaca vrstva stále nemusí dovoliť vstup.

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
        "chart_state_base": "BASE",
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
        "compare_desc": "Comparison of the main strategy, the reference strategy and BTC Buy & Hold without internal research labels.",
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

If conditions are strong enough, the strategy then evaluates a set of candidate assets and scores them using multiple inputs, especially trend, return strength, risk, and volatility.  
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
It means the market is still below the internal quality threshold, or no candidate is strong enough to justify real exposure.

That is why the system may have an internal leader while still not taking the trade.  
A candidate may exist, but the governance and safety layer may still block execution.

### What makes this strategy different

This is not just a simple ranking model.  
The strategy has three layers:

- **Market regime filter** – decides whether risk should be on at all
- **Asset selection layer** – finds the strongest valid candidate
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
    "Top karty zobrazuju aktualne metriky z Production Core snapshotu. "
    "Nejde o samostatny compare/ranking vystup a vysledky uz "
    "zahrnaju Hyperliquid poplatky."
)
TEXT["en"]["performance_fee_note"] = (
    "Top cards show the current metrics from the Production Core snapshot. "
    "They are not fed by a separate compare/ranking "
    "artifact, and results already include Hyperliquid fees."
)
TEXT["sk"]["chart_note_strip_hidden"] = (
    "Horna krivka ukazuje vykon hlavneho modelu proti BTC benchmarku. "
    "Spodny pas je skryty, pretoze canonical paper rows momentalne "
    "nedovoluju pravdive zobrazenie drzaneho stavu."
)
TEXT["en"]["chart_note_strip_hidden"] = (
    "The top line shows the main model versus the BTC benchmark. "
    "The lower strip is hidden because the canonical paper rows do not "
    "currently allow a truthful held-state rendering."
)
TEXT["sk"].update(
    {
        "production_core_error_prefix": "Production Core v1 homepage blocked",
        "production_exposure": "Expozicia",
        "production_closed_day": "Posledny uzavrety den",
        "production_next_rebalance": "Najblizsi rebalance",
        "production_chart_note": "Horna krivka ukazuje equity seriu priamo z Production Core timeseries bez legacy fallbacku.",
        "production_reason_title": "Preco je strategia v tomto stave",
        "production_wait_title": "Na co strategia caka",
        "production_pain_title": "Aktualne pain points",
        "production_recent_rebalances": "Nedavne rebalance udalosti",
        "production_recent_regimes": "Nedavne zmeny rezimu",
        "production_wait_current": "Aktualne hodnoty",
        "production_wait_target": "Cielova podmienka",
        "production_signal_health": "Signal health",
        "production_validation_passed": "Production Core validacia presla",
        "production_validation_failed": "Production Core validacia zlyhala",
        "production_waiting_yes": "Ano",
        "production_waiting_no": "Nie",
    }
)
TEXT["en"].update(
    {
        "production_core_error_prefix": "Production Core v1 homepage blocked",
        "production_exposure": "Exposure",
        "production_closed_day": "Last closed day",
        "production_next_rebalance": "Next rebalance",
        "production_chart_note": "The top line shows the equity series directly from the Production Core timeseries with no legacy fallback.",
        "production_reason_title": "Why the strategy is in this state",
        "production_wait_title": "What the strategy is waiting for",
        "production_pain_title": "Current pain points",
        "production_recent_rebalances": "Recent rebalance events",
        "production_recent_regimes": "Recent regime changes",
        "production_wait_current": "Current values",
        "production_wait_target": "Target condition",
        "production_signal_health": "Signal health",
        "production_validation_passed": "Production Core validation passed",
        "production_validation_failed": "Production Core validation failed",
        "production_waiting_yes": "Yes",
        "production_waiting_no": "No",
    }
)
METRIC_HELP["sk"].update(
    {
        TEXT["sk"]["cagr"]: (
            "Tato top karta ukazuje aktualny CAGR priamo z Production Core snapshotu."
        ),
        TEXT["sk"]["since2023"]: (
            "Tato top karta ukazuje okno CAGR od 2023 priamo z Production Core snapshotu."
        ),
        TEXT["sk"]["since2025"]: (
            "Tato top karta ukazuje okno CAGR od 2025 priamo z Production Core snapshotu."
        ),
        TEXT["sk"]["currently_holding"]: "Toto pole ide priamo z Production Core snapshotu ako oficialny aktualny asset.",
        TEXT["sk"]["trend_state"]: "Textovy trend stav ide z Production Core snapshotu, nie z legacy live exportu.",
        TEXT["sk"]["trend_score"]: "Trend score je z Production Core snapshotu a jeho historia z Production Core timeseries.",
        TEXT["sk"]["buy_threshold"]: "Buy threshold sa cita z posledneho validovaneho riadku Production Core timeseries.",
        TEXT["sk"]["total_return"]: "Celkovy vynos je citany z Production Core snapshot metrics.",
        TEXT["sk"]["max_dd"]: "Max drawdown je citany z Production Core snapshot metrics.",
        TEXT["sk"]["switch_count"]: "Pocet prepnuti je citany z Production Core snapshot metrics.",
        TEXT["sk"]["cash_days"]: "Cash Days su citane z Production Core snapshot metrics.",
        TEXT["sk"]["btc_days"]: "BTC Days su citane z Production Core snapshot metrics.",
        TEXT["sk"]["production_exposure"]: "Expozicia ide priamo z Production Core snapshotu ako aktualne oficialne nastavenie.",
        TEXT["sk"]["production_closed_day"]: "Posledny uzavrety den ide z Production Core snapshotu a musi sediet s diagnostics aj timeseries.",
    }
)
METRIC_HELP["en"].update(
    {
        TEXT["en"]["cagr"]: (
            "This top card shows the current CAGR directly from the Production Core snapshot."
        ),
        TEXT["en"]["since2023"]: (
            "This top card shows the since-2023 CAGR directly from the Production Core snapshot."
        ),
        TEXT["en"]["since2025"]: (
            "This top card shows the since-2025 CAGR directly from the Production Core snapshot."
        ),
        TEXT["en"]["currently_holding"]: "This field is read directly from the Production Core snapshot as the official current asset.",
        TEXT["en"]["trend_state"]: "The trend state is read from the Production Core snapshot, not from the legacy live export.",
        TEXT["en"]["trend_score"]: "The trend score comes from the Production Core snapshot and its history from the Production Core timeseries.",
        TEXT["en"]["buy_threshold"]: "The buy threshold is read from the latest validated row of the Production Core timeseries.",
        TEXT["en"]["total_return"]: "Total return is read from the Production Core snapshot metrics.",
        TEXT["en"]["max_dd"]: "Max drawdown is read from the Production Core snapshot metrics.",
        TEXT["en"]["switch_count"]: "Switch count is read from the Production Core snapshot metrics.",
        TEXT["en"]["cash_days"]: "Cash Days are read from the Production Core snapshot metrics.",
        TEXT["en"]["btc_days"]: "BTC Days are read from the Production Core snapshot metrics.",
        TEXT["en"]["production_exposure"]: "Exposure comes directly from the Production Core snapshot as the official current setting.",
        TEXT["en"]["production_closed_day"]: "The last closed day comes from the Production Core snapshot and must match diagnostics and timeseries.",
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


def stop_for_production_homepage_block(message: str) -> None:
    lang = st.session_state.get("lang", "sk")
    st.error(
        f"{t(lang, 'load_failed')}: {t(lang, 'production_core_error_prefix')}: {message}"
    )
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
        "held_asset",
        "exposure",
        "regime",
        "execution_state",
        "trend_state",
        "trend_score",
        "buy_threshold",
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
        "trend_score",
        "buy_threshold",
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
        frame.dropna(subset=["ts", "equity"])
        .sort_values("ts")
        .drop_duplicates(subset=["ts"], keep="last")
        .reset_index(drop=True)
    )
    if frame.empty:
        stop_for_production_homepage_block("timeseries has no usable rows")
    return frame


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
        snapshot.get("trend_score"),
        last_row.get("trend_score"),
        field_name="trend_score",
        abs_tol=1e-6,
    )

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
        st.error(
            f"{t(st.session_state.get('lang', 'sk'), 'load_failed')}: "
            f"{path} is not {expected_type}"
        )
        st.stop()
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
    "current": "Current: the latest authority publish is aligned with the latest closed UTC day.",
    "stale": "Stale: the latest authority snapshot is behind the latest closed UTC day.",
    "refresh_in_progress": "Authority refresh in progress: the latest Pi publish attempt is still running.",
    "refresh_failed": "Authority refresh failed: the latest Pi publish attempt failed.",
    "missing_authority_artifact": "Missing authority artifact: latest_attempt_status.json is missing or invalid.",
}


def _derive_authority_currentness(
    latest_successful_snapshot: dict,
    latest_attempt_status: dict,
) -> tuple[str, str, Path, str]:
    attempt_payload = latest_attempt_status if isinstance(latest_attempt_status, dict) else {}
    success_payload = latest_successful_snapshot if isinstance(latest_successful_snapshot, dict) else {}

    def first_present(*values: Any) -> str | None:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    def source_details(using_attempt_payload: bool) -> tuple[Path, str]:
        if using_attempt_payload:
            return AUTHORITY_LATEST_ATTEMPT_STATUS_PATH, ATTEMPT_STATUS_ARTIFACT_TYPE
        return AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH, SUCCESS_SNAPSHOT_ARTIFACT_TYPE

    attempt_status = first_present(
        attempt_payload.get("latest_authoritative_attempt_status"),
        success_payload.get("latest_authoritative_attempt_status"),
    )
    normalized_attempt_status = str(attempt_status or "").strip().lower()

    if normalized_attempt_status == "in_progress":
        source_path, source_type = source_details(bool(attempt_payload))
        return "refresh_in_progress", FRESHNESS_SUMMARY_TEXT["refresh_in_progress"], source_path, source_type

    if normalized_attempt_status == "failed":
        source_path, source_type = source_details(bool(attempt_payload))
        attempt_error = first_present(
            attempt_payload.get("latest_authoritative_attempt_error"),
            success_payload.get("latest_authoritative_attempt_error"),
        )
        reason = FRESHNESS_SUMMARY_TEXT["refresh_failed"]
        if attempt_error:
            reason = f"{reason} error={attempt_error}."
        return "refresh_failed", reason, source_path, source_type

    attempt_target_day = first_present(attempt_payload.get("target_closed_day_utc"))
    attempt_strategy_day = first_present(attempt_payload.get("strategy_artifact_closed_day_utc"))
    success_target_day = first_present(success_payload.get("target_closed_day_utc"))
    success_strategy_day = first_present(success_payload.get("strategy_artifact_closed_day_utc"))

    if attempt_target_day and attempt_strategy_day:
        target_closed_day_utc = attempt_target_day
        strategy_artifact_closed_day_utc = attempt_strategy_day
        source_path, source_type = source_details(True)
    elif success_target_day and success_strategy_day:
        target_closed_day_utc = success_target_day
        strategy_artifact_closed_day_utc = success_strategy_day
        source_path, source_type = source_details(False)
    else:
        target_closed_day_utc = first_present(attempt_target_day, success_target_day)
        strategy_artifact_closed_day_utc = first_present(
            attempt_strategy_day,
            success_strategy_day,
        )
        source_path, source_type = source_details(bool(attempt_target_day or attempt_strategy_day or attempt_payload))

    if target_closed_day_utc and strategy_artifact_closed_day_utc:
        if target_closed_day_utc == strategy_artifact_closed_day_utc:
            return (
                "current",
                (
                    "Current: authority target closed UTC day "
                    f"{target_closed_day_utc} matches authority strategy artifact closed UTC day "
                    f"{strategy_artifact_closed_day_utc}."
                ),
                source_path,
                source_type,
            )
        return (
            "stale",
            (
                "Stale: authority target closed UTC day "
                f"{target_closed_day_utc} does not match authority strategy artifact closed UTC day "
                f"{strategy_artifact_closed_day_utc}."
            ),
            source_path,
            source_type,
        )

    if target_closed_day_utc:
        return (
            "stale",
            (
                "Stale: authority target closed UTC day "
                f"{target_closed_day_utc} is present but authority strategy artifact closed UTC day is missing."
            ),
            source_path,
            source_type,
        )

    if normalized_attempt_status == "success":
        return (
            "stale",
            "Stale: authority publish succeeded but target/strategy closed UTC day fields are missing.",
            source_path,
            source_type,
        )

    source_path, source_type = source_details(bool(attempt_payload))
    return "missing_authority_artifact", FRESHNESS_SUMMARY_TEXT["missing_authority_artifact"], source_path, source_type


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


def build_authority_runtime_table_snapshot(
    latest_successful_snapshot: dict,
    latest_attempt_status: dict,
) -> dict:
    attempt_payload = latest_attempt_status if isinstance(latest_attempt_status, dict) else {}
    success_payload = latest_successful_snapshot if isinstance(latest_successful_snapshot, dict) else {}
    source_path = (
        AUTHORITY_LATEST_ATTEMPT_STATUS_PATH
        if attempt_payload
        else AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH
    )
    source_type = (
        ATTEMPT_STATUS_ARTIFACT_TYPE
        if attempt_payload
        else SUCCESS_SNAPSHOT_ARTIFACT_TYPE
    )
    authority_generated_at_utc = (
        attempt_payload.get("generated_at_utc")
        or attempt_payload.get("refresh_finished_at_utc")
        or success_payload.get("generated_at_utc")
        or success_payload.get("refresh_finished_at_utc")
    )
    authority_run_id = attempt_payload.get("run_id") or success_payload.get("run_id")
    authority_attempt_status = (
        str(
            attempt_payload.get("latest_authoritative_attempt_status")
            or success_payload.get("latest_authoritative_attempt_status")
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
        success_payload,
        attempt_payload,
    )
    wallet_sync_utc = (
        attempt_payload.get("authority_wallet_sync_utc")
        or attempt_payload.get("authority_account_snapshot_as_of_utc")
    )
    wallet_source_path = AUTHORITY_LATEST_ATTEMPT_STATUS_PATH
    wallet_source_type = ATTEMPT_STATUS_ARTIFACT_TYPE
    if not wallet_sync_utc:
        wallet_sync_utc = (
            success_payload.get("authority_wallet_sync_utc")
            or success_payload.get("authority_account_snapshot_as_of_utc")
        )
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
    if raw in {"CASH", "0", "0.0", "0.00", "ZERO", "ZERO EXPOSURE", "ZERO_EXPOSURE"}:
        return t(lang, "cash")
    return raw


def resolve_homepage_held_state(live_public_state: dict[str, Any], lang: str) -> str:
    held_asset_public = live_public_state.get("held_asset_public")
    execution_state = str(live_public_state.get("execution_state") or "").strip().upper()
    portfolio_held_asset = str(live_public_state.get("portfolio_held_asset") or "").strip().upper()
    baseline_held_asset = str(live_public_state.get("baseline_held_asset") or "").strip().upper()
    tradable_governed_asset = str(live_public_state.get("tradable_governed_asset") or "").strip().upper()
    cash_day = as_bool(live_public_state.get("cash_day"))

    cash_like_tokens = {"", "0", "0.0", "0.00", "CASH", "BASELINE_RISK", "EARLY_RISK", "FULL_RISK", "NONE", "NULL"}

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
        "phase68i_dynamic_ladder_candidate": {"sk": "Dynamická leverage škála", "en": "Dynamic leverage ladder"},
        "phase68g_66g_1p25x_candidate": {"sk": "Statický 1.25x fallback", "en": "Static 1.25x fallback"},
    }
    return mapping.get(raw, {"sk": str(value), "en": str(value)})[lang]


def prettify_execution_profile(value: str | None, lang: str) -> str:
    if value is None:
        return t(lang, "na")
    raw = str(value).strip().lower()
    mapping = {
        "unlevered": {"sk": "Bez leverage", "en": "Without leverage"},
        "none": {"sk": "Bez leverage", "en": "Without leverage"},
        "dynamic_ladder": {"sk": "Dynamická leverage škála", "en": "Dynamic leverage ladder"},
        "static_1p25x": {"sk": "Statický 1.25x fallback", "en": "Static 1.25x fallback"},
        "phase68g_66g_1p25x_candidate": {"sk": "Statický 1.25x fallback", "en": "Static 1.25x fallback"},
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
    buy_threshold = as_float(last_row.get("buy_threshold"))
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
    history = timeseries_df[["ts", "trend_score", "buy_threshold"]].copy()
    history = history.dropna(subset=["ts", "trend_score", "buy_threshold"]).reset_index(drop=True)
    return history


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
            bucket = "BASE"
            label = t(lang, "chart_state_base")
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
        "Varovanie: spodny pas homepage chartu bol zablokovany, pretoze canonical paper "
        "riadky maju nezhodu medzi drzanym stavom a cash / nulovou pohybovou semantikou "
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
    return token in {"", "CASH", "USD", "USDT", "NONE", "NULL", "ZERO", "ZERO_EXPOSURE"}


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
) -> go.Figure:
    main_plot = filter_from_year(timeseries_df, year).copy()
    if main_plot.empty:
        raise ValueError("homepage production chart has no rows for the selected year")

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
runtime_snapshot_source_path = (
    AUTHORITY_LATEST_ATTEMPT_STATUS_PATH
    if latest_attempt_status_payload.get("app_runtime_snapshot")
    else AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH
)
runtime_authority_payload = (
    latest_attempt_status_payload
    if runtime_snapshot_source_path == AUTHORITY_LATEST_ATTEMPT_STATUS_PATH
    else latest_successful_snapshot_payload
)
runtime_snapshot = load_runtime_snapshot_for_app(
    dict(
        latest_attempt_status_payload.get("app_runtime_snapshot")
        or latest_successful_snapshot_payload.get("app_runtime_snapshot")
        or {}
    ),
    runtime_snapshot_source_path,
)
selector_cfg = build_selector_config_from_snapshot(product_snapshot, runtime_snapshot)

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
account_status_payload = dict(runtime_snapshot.get("execution_status") or {})
account_snapshot_payload = dict(runtime_snapshot.get("account_snapshot_summary") or {})
account_snapshot_view = dict(account_snapshot_payload)
runtime_health_payload = dict(runtime_snapshot.get("runtime_health_summary") or {})
dry_run_decision_payload = dict(runtime_snapshot.get("dry_run_summary") or {})
real_order_gate_payload = dict(runtime_snapshot.get("gate_summary") or {})
execution_mode_payload = dict(runtime_snapshot.get("execution_mode_posture") or {})
live_order_policy_payload = dict(runtime_snapshot.get("live_order_policy_summary") or {})
trading_operation_mode_payload = dict(execution_mode_payload.get("trading_operation_mode") or {})
runtime_last_sync_utc = runtime_snapshot.get("runtime_last_sync_utc")
account_snapshot_as_of_utc = runtime_snapshot.get("account_snapshot_as_of_utc")
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
top_performance_metrics = dict(main_metrics)

years = available_years_from_frames([production_timeseries_df])
if not years:
    st.error(f"{t(lang, 'load_failed')}: no usable dates")
    st.stop()

main_equity_df = production_timeseries_df[["ts", "equity"]].dropna().copy()

tabs = st.tabs(t(lang, "tabs"))

with tabs[0]:
    trade_count_label = "Pocet obchodov" if lang == "sk" else "Trade count"
    current_drawdown_label = "Aktualny drawdown" if lang == "sk" else "Current drawdown"
    reason_text = str(
        production_diagnostics.get("latest_state_explanation")
        or get_nested_value(production_snapshot, "decision_context", "current_reason_text")
        or ""
    ).strip()
    wait_condition = dict(production_diagnostics.get("current_wait_condition") or {})
    current_trade_state = dict(production_diagnostics.get("current_trade_state") or {})
    pain_points = list(production_diagnostics.get("current_pain_points") or [])
    recent_rebalance_rows = [
        {
            "Date" if lang == "en" else "Datum": format_date_text(item.get("date"), lang),
            "Asset": safe_text_value(item.get("held_asset"), lang=lang),
            "Exposure" if lang == "en" else "Expozicia": safe_text_value(item.get("exposure"), lang=lang),
            "Reason" if lang == "en" else "Dovod": safe_text_value(item.get("reason_code"), lang=lang),
        }
        for item in list(production_diagnostics.get("recent_rebalance_events") or [])[:5]
    ]
    recent_regime_rows = [
        {
            "Date" if lang == "en" else "Datum": format_date_text(item.get("date"), lang),
            "Asset": safe_text_value(item.get("held_asset"), lang=lang),
            "Regime": safe_text_value(item.get("regime"), lang=lang),
            "Reason" if lang == "en" else "Dovod": safe_text_value(item.get("reason_code"), lang=lang),
        }
        for item in list(production_diagnostics.get("recent_regime_changes") or [])[:5]
    ]

    home_cards = [
        {
            "label": t(lang, "currently_holding"),
            "value": safe_text_value(production_snapshot.get("current_asset"), lang=lang),
            "subtitle": safe_text_value(production_snapshot.get("current_regime"), lang=lang),
            "help": METRIC_HELP[lang][t(lang, "currently_holding")],
            "accent": "blue",
        },
        {
            "label": t(lang, "production_exposure"),
            "value": f"{as_float(production_snapshot.get('current_exposure')):.2f}x" if as_float(production_snapshot.get("current_exposure")) is not None else t(lang, "na"),
            "subtitle": safe_text_value(production_snapshot.get("execution_state"), lang=lang),
            "help": METRIC_HELP[lang][t(lang, "production_exposure")],
            "accent": "green",
        },
        {
            "label": t(lang, "trend_state"),
            "value": safe_text_value(trend_live.get("trend_state_label"), lang=lang),
            "subtitle": safe_metric_text(trend_live.get("trend_score"), decimals=4, suffix="", lang=lang),
            "help": METRIC_HELP[lang][t(lang, "trend_state")],
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

    st.markdown(f"### {t(lang, 'chart_title')}")
    selected_year_home = st.selectbox(
        t(lang, "chart_year"),
        options=years,
        index=years.index(2025) if 2025 in years else 0,
        key="selected_year_home",
    )
    st.plotly_chart(
        make_production_equity_chart(
            timeseries_df=production_timeseries_df,
            year=selected_year_home,
            lang=lang,
            main_label=labels.get(main_key, main_key),
            title=t(lang, "chart_title"),
        ),
        width="stretch",
    )
    st.caption(t(lang, "production_chart_note"))
    st.markdown(f"### {t(lang, 'performance_title')}")
    st.caption(t(lang, "performance_fee_note"))
    perf1 = st.columns(3)
    with perf1[0]:
        render_color_card(t(lang, "cagr"), safe_metric_text(top_performance_metrics.get("cagr_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "cagr")], "blue")
    with perf1[1]:
        render_color_card(t(lang, "since2023"), safe_metric_text(top_performance_metrics.get("since2023_cagr_pct"), lang=lang), "CAGR", METRIC_HELP[lang][t(lang, "since2023")], "green")
    with perf1[2]:
        render_color_card(t(lang, "since2025"), safe_metric_text(top_performance_metrics.get("since2025_cagr_pct"), lang=lang), "CAGR", METRIC_HELP[lang][t(lang, "since2025")], "violet")

    perf2 = st.columns(3)
    with perf2[0]:
        render_color_card(t(lang, "max_dd"), safe_metric_text(main_metrics.get("max_drawdown_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "max_dd")], "orange")
    with perf2[1]:
        render_color_card(t(lang, "total_return"), safe_metric_text(main_metrics.get("total_return_pct"), lang=lang), "", METRIC_HELP[lang][t(lang, "total_return")], "neutral")
    with perf2[2]:
        render_color_card(trade_count_label, safe_int_text(main_metrics.get("trade_count"), lang=lang), "", "", "neutral")

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
        render_color_card(current_drawdown_label, safe_metric_text(get_nested_value(production_snapshot, "decision_context", "current_drawdown_pct"), lang=lang), "", "", "violet")

    st.markdown(f"### {t(lang, 'production_reason_title')}")
    diag_cols = st.columns(3)
    with diag_cols[0]:
        st.info(reason_text or t(lang, "na"))
        validation_label = (
            t(lang, "production_validation_passed")
            if str(production_quality.get("status") or "").strip().lower() == "passed"
            else t(lang, "production_validation_failed")
        )
        st.caption(
            f"{t(lang, 'production_signal_health')}: {validation_label} | "
            f"{safe_text_value(production_snapshot.get('strategy_version'), lang=lang)}"
        )
    with diag_cols[1]:
        st.markdown(f"#### {t(lang, 'production_wait_title')}")
        st.write(
            str(wait_condition.get("text") or current_trade_state.get("waiting_reason_text") or t(lang, "na"))
        )
        st.caption(
            f"{'Waiting' if lang == 'en' else 'Cakanie'}: "
            f"{t(lang, 'production_waiting_yes') if as_bool(current_trade_state.get('is_waiting')) else t(lang, 'production_waiting_no')}"
        )
        wait_current_rows = [
            {"Field" if lang == "en" else "Pole": key, "Value" if lang == "en" else "Hodnota": safe_text_value(value, lang=lang)}
            for key, value in dict(wait_condition.get("current_values") or {}).items()
        ]
        wait_target_rows = [
            {"Field" if lang == "en" else "Pole": key, "Value" if lang == "en" else "Hodnota": safe_text_value(value, lang=lang)}
            for key, value in dict(wait_condition.get("target_condition") or {}).items()
        ]
        if wait_current_rows:
            st.caption(t(lang, "production_wait_current"))
            render_app_table(wait_current_rows, emphasize_first_column=True)
        if wait_target_rows:
            st.caption(t(lang, "production_wait_target"))
            render_app_table(wait_target_rows, emphasize_first_column=True)
    with diag_cols[2]:
        st.markdown(f"#### {t(lang, 'production_pain_title')}")
        if pain_points:
            for pain_point in pain_points:
                severity = safe_text_value(pain_point.get("severity"), lang=lang).upper()
                st.markdown(f"- **{severity}** {safe_text_value(pain_point.get('text'), lang=lang)}")
        else:
            st.caption(t(lang, "na"))

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
    pi_runtime_update_utc = runtime_table_payload.get("last_pi_update_utc")
    wallet_sync_utc = runtime_table_payload.get("last_wallet_sync_utc")
    refresh_label_column = "Preh\u013ead" if lang == "sk" else "Field"
    refresh_value_column = "Hodnota" if lang == "sk" else "Value"
    refresh_rows = [
        {
            refresh_label_column: "Posledn\u00e9 autoritativne publikovanie z Pi" if lang == "sk" else "Latest Pi authority publish",
            refresh_value_column: format_local_time_text(
                pi_runtime_update_utc,
                lang,
            ),
        },
        {
            refresh_label_column: "Stav posledneho autoritativneho pokusu" if lang == "sk" else "Latest authority attempt status",
            refresh_value_column: safe_text_value(
                runtime_table_payload.get("last_refresh_status"),
                lang=lang,
            ),
        },
        {
            refresh_label_column: "ID posledneho autoritativneho pokusu" if lang == "sk" else "Latest authority attempt ID",
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
            refresh_label_column: "Autoritativna aktualnost" if lang == "sk" else "Authority currentness",
            refresh_value_column: safe_text_value(
                refresh_currentness_state,
                lang=lang,
            ),
        },
        {
            refresh_label_column: "D\u00f4vod stavu" if lang == "sk" else "Reason",
            refresh_value_column: safe_text_value(
                refresh_currentness_reason,
                lang=lang,
            ),
        },
    ]
    with st.expander("Stav dát", expanded=False):
        st.markdown("#### Autoritativny runtime" if lang == "sk" else "#### Authority Runtime")
        render_app_table(refresh_rows, emphasize_first_column=True)

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

        st.markdown("#### Stav a ovládanie")
        with st.container(border=True):
            render_ops_strip(
                [
                    {
                        "label": "Stav stratégie" if lang == "sk" else "Strategy state",
                        "value": operation_mode_label,
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




