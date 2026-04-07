from __future__ import annotations

import html
import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scripts.execution.trading_operation_mode import (
    DEFAULT_TRADING_OPERATION_MODE_PATH,
    load_trading_operation_mode_payload,
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
BTC_FILE = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
DEFAULT_EXECUTION_STATUS_PATH = "outputs/execution/live_status/execution_status.json"
DEFAULT_ACCOUNT_SNAPSHOT_PATH = "outputs/execution/read_only/hyperliquid_account_snapshot.json"
DEFAULT_RUNTIME_HEALTH_PATH = "outputs/execution/runtime_health/latest_runtime_health.json"
DEFAULT_DRY_RUN_DECISION_PATH = "outputs/execution/dry_run/latest_dry_run_decision.json"
DEFAULT_REAL_ORDER_GATE_PATH = "outputs/execution/live_gate/latest_real_order_gate_decision.json"
EXECUTION_MODE_CONFIG_PATH = ROOT / "execution" / "config" / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = ROOT / "execution" / "config" / "live_order_policy.json"
TRADING_OPERATION_MODE_CONFIG_PATH = DEFAULT_TRADING_OPERATION_MODE_PATH
LIVE_ORDER_CONFIRMATION_TEXT = "POTVRDZUJEM"

CONTACT_DIR = ROOT / "contact"
CONTACT_CSV = CONTACT_DIR / "contact_log.csv"

EXPORT_CONTRACT_PATH = ROOT / "source_of_truth" / "export_contract.json"

DEFAULT_SELECTOR = {
    "product_name": "TrendAtlas Crypto",
    "main_strategy_model": "phase68i_dynamic_ladder_candidate",
    "reference_strategy_model": "phase67j_no_neo_main",
    "benchmark": "BTC",
    "main_model_key": "phase68i_dynamic_ladder_candidate",
    "reference_model_key": "phase67j_no_neo_main",
    "benchmark_label": "BTC",
    "compare_model_keys": [
        "phase68i_dynamic_ladder_candidate",
        "phase67j_no_neo_main",
    ],
    "display_names": {
        "phase68i_dynamic_ladder_candidate": {
            "sk": "Hlavná stratégia",
            "en": "Main strategy",
        },
        "phase67j_no_neo_main": {
            "sk": "Referenčná stratégia",
            "en": "Reference strategy",
        },
        "phase66g_production_soft_filters": {
            "sk": "Trend / core vrstva",
            "en": "Trend / core layer",
        },
    },
    "model_sources": {
        "phase68i_dynamic_ladder_candidate": {
            "summary_path": "outputs/execution/app_exports/phase68i_dynamic_ladder_candidate_summary.csv",
            "paper_path": "outputs/execution/app_exports/phase68i_dynamic_ladder_candidate_paper.csv",
            "live_status_path": "outputs/execution/app_exports/phase67j_live_status.csv",
        },
        "phase67j_no_neo_main": {
            "summary_path": "outputs/execution/app_exports/phase67j_final_narrow_validation_summary.csv",
            "paper_path": "outputs/execution/app_exports/phase67j_no_neo_main_paper.csv",
            "live_status_path": "outputs/execution/app_exports/phase67j_live_status.csv",
        },
        "phase66g_production_soft_filters": {
            "summary_path": "outputs/execution/app_exports/phase66g_production_candidate_summary.csv",
            "paper_path": "outputs/execution/app_exports/phase66g_production_soft_filters_paper.csv",
            "live_status_path": "outputs/execution/app_exports/phase66g_live_status.csv",
        },
    },
    "trend_barometer_source": {
        "live_status_path": "outputs/execution/app_exports/phase66g_live_status.csv",
        "history_path": "outputs/execution/app_exports/phase66g_trend_barometer_history.csv",
        "model_key": "phase66g_production_soft_filters",
    },
    "app_live_mode_contract": {
        "current": {
            "live_truth_mode": "phase68i_dynamic_ladder_candidate",
            "execution_profile": "dynamic_ladder",
            "leverage_mode": "dynamic",
            "deployment_candidate_label": "phase68i_dynamic_ladder_candidate",
            "fallback_profile_label": "phase68g_66g_1p25x_candidate",
            "approval_gate_status": "approved_and_applied",
            "real_order_gate_status": "live_order_enabled_and_approved",
            "real_order_eligible_status": "live_order_enabled_and_approved",
        }
    },
    "account_observability_contract": {
        "current": {
            "enabled": True,
            "status_json_path": DEFAULT_EXECUTION_STATUS_PATH,
            "snapshot_json_path": DEFAULT_ACCOUNT_SNAPSHOT_PATH,
            "read_mode": "read_only_operational_view",
            "execution_proof_state_label": {
                "sk": "Execution proof zatiaľ nie je oficiálne potvrdený",
                "en": "Execution proof is not officially confirmed yet",
            },
            "placeholder_framing": {
                "sk": (
                    "Tento dashboard je read-only prevádzkový observability prehľad. "
                    "Zobrazuje aktuálne operational artifacts bez tvrdenia, že live execution "
                    "spoľahlivosť je už plne potvrdená."
                ),
                "en": (
                    "This dashboard is a read-only operational observability view. "
                    "It surfaces current operational artifacts without claiming that live "
                    "execution reliability has already been fully confirmed."
                ),
            },
            "ui_sections": [
                "proof_banner",
                "overview",
                "balances",
                "positions",
                "activity",
            ],
        }
    },
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
        "home_title": "Dnes v skratke",
        "currently_holding": "Momentálne držíme",
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
        "trend_cross_none": "Bez dnešného prechodu",
        "na": "Nedostupné",
        "chart_title": "Vývoj kapitálu",
        "chart_note": "Graf ukazuje hlavnú stratégiu a BTC benchmark bez referenčnej stratégie.",
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
        "home_title": "Today at a glance",
        "currently_holding": "Currently holding",
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
        "trend_cross_none": "No cross today",
        "na": "Unavailable",
        "chart_title": "Capital curve",
        "chart_note": "The chart shows the main strategy and the BTC benchmark, without the reference strategy.",
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
        "Momentálne držíme": "Toto pole ide priamo z live CSV cez held_asset_public. App si ho sama nedopočítava.",
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
        "Currently holding": "This field is read directly from held_asset_public in the live CSV.",
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
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


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
                "Rezim obchodovania je nastaveny na automaticke obchody."
                if mode == "automatic"
                else "Rezim obchodovania je nastaveny na manualne obchody."
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
            border-radius: 18px;
            padding: 8px 10px;
            box-shadow: 0 10px 28px rgba(0,0,0,0.18);
        }

        div[data-testid="stDataFrame"] {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow: 0 10px 28px rgba(0,0,0,0.16);
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


def extract_app_export_contract(raw_payload: dict | None) -> dict:
    if not isinstance(raw_payload, dict):
        return {}
    contract = raw_payload.get("app_export_contract")
    if isinstance(contract, dict):
        return contract
    return raw_payload


def extract_account_observability_contract(raw_payload: dict | None) -> dict:
    if not isinstance(raw_payload, dict):
        return {}
    contract = raw_payload.get("account_observability_contract")
    return contract if isinstance(contract, dict) else {}


def merge_selector_config(raw_selector: dict | None) -> dict:
    merged = json.loads(json.dumps(DEFAULT_SELECTOR))
    selector = extract_app_export_contract(raw_selector)
    observability_contract = extract_account_observability_contract(raw_selector)
    if not selector:
        selector = {}

    merged.update(selector)
    merged["main_model_key"] = selector.get("main_model_key") or selector.get("main_strategy_model") or merged.get("main_model_key")
    merged["reference_model_key"] = selector.get("reference_model_key") or selector.get("reference_strategy_model") or merged.get("reference_model_key")
    merged["benchmark_label"] = selector.get("benchmark_label") or selector.get("benchmark") or merged.get("benchmark_label")

    for nested_key in ["display_names", "model_sources", "trend_barometer_source", "app_live_mode_contract"]:
        merged[nested_key] = {
            **DEFAULT_SELECTOR.get(nested_key, {}),
            **(selector.get(nested_key, {}) or {}),
        }

    default_live_mode_current = ((DEFAULT_SELECTOR.get("app_live_mode_contract") or {}).get("current") or {})
    selector_live_mode_current = ((selector.get("app_live_mode_contract") or {}).get("current") or {})
    if default_live_mode_current or selector_live_mode_current:
        merged["app_live_mode_contract"]["current"] = {
            **default_live_mode_current,
            **selector_live_mode_current,
        }

    merged["account_observability_contract"] = {
        **DEFAULT_SELECTOR.get("account_observability_contract", {}),
        **observability_contract,
    }
    default_observability_current = ((DEFAULT_SELECTOR.get("account_observability_contract") or {}).get("current") or {})
    selector_observability_current = (observability_contract.get("current") or {})
    merged["account_observability_contract"]["current"] = {
        **default_observability_current,
        **selector_observability_current,
    }

    default_placeholder_framing = default_observability_current.get("placeholder_framing")
    selector_placeholder_framing = selector_observability_current.get("placeholder_framing")
    if isinstance(default_placeholder_framing, dict) or isinstance(selector_placeholder_framing, dict):
        merged["account_observability_contract"]["current"]["placeholder_framing"] = {
            **(default_placeholder_framing if isinstance(default_placeholder_framing, dict) else {}),
            **(selector_placeholder_framing if isinstance(selector_placeholder_framing, dict) else {}),
        }

    if not merged.get("compare_model_keys"):
        merged["compare_model_keys"] = [
            key for key in [merged.get("main_model_key"), merged.get("reference_model_key")] if key
        ]

    return merged


def load_selector_config() -> dict:
    if not EXPORT_CONTRACT_PATH.exists():
        return json.loads(json.dumps(DEFAULT_SELECTOR))

    try:
        with open(EXPORT_CONTRACT_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_SELECTOR))

    return merge_selector_config(raw)


def get_current_live_mode_contract(contract_cfg: dict | None) -> dict:
    default_current = ((DEFAULT_SELECTOR.get("app_live_mode_contract") or {}).get("current") or {})
    selector_current = (((contract_cfg or {}).get("app_live_mode_contract") or {}).get("current") or {})
    return {
        **default_current,
        **selector_current,
    }


def get_current_account_observability_contract(contract_cfg: dict | None) -> dict:
    default_current = ((DEFAULT_SELECTOR.get("account_observability_contract") or {}).get("current") or {})
    selector_current = (((contract_cfg or {}).get("account_observability_contract") or {}).get("current") or {})
    merged = {
        **default_current,
        **selector_current,
    }

    default_placeholder_framing = default_current.get("placeholder_framing")
    selector_placeholder_framing = selector_current.get("placeholder_framing")
    if isinstance(default_placeholder_framing, dict) or isinstance(selector_placeholder_framing, dict):
        merged["placeholder_framing"] = {
            **(default_placeholder_framing if isinstance(default_placeholder_framing, dict) else {}),
            **(selector_placeholder_framing if isinstance(selector_placeholder_framing, dict) else {}),
        }

    ui_sections = merged.get("ui_sections") or []
    merged["ui_sections"] = [str(section).strip() for section in ui_sections if str(section).strip()]
    return merged


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


def load_model_paper(paper_dir_str: str | None, model_key: str, explicit_paper_path: str | None = None) -> pd.DataFrame:
    candidates: list[Path] = []

    explicit_path = normalize_path(explicit_paper_path)
    if explicit_path is not None:
        candidates.append(explicit_path)

    paper_dir = normalize_path(paper_dir_str)
    if paper_dir is not None:
        candidates.extend([
            paper_dir / f"{model_key}_paper.csv",
            paper_dir / f"{model_key}.csv",
        ])

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
    if not row.empty:
        return row.iloc[0]

    if len(df) == 1:
        return df.iloc[0]

    return None


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
    if "cash_day" in df.columns:
        cash_series = df["cash_day"].map(as_bool).dropna()
        if not cash_series.empty:
            return as_float(cash_series.astype(float).mean() * 100.0)

    for col in [
        "portfolio_held_asset",
        "selected_coin",
        "symbol",
        "asset",
        "holding",
        "position",
        "leader",
        "tradable_governed_asset",
        "baseline_held_asset",
    ]:
        if col in df.columns:
            s = df[col].astype(str).str.upper().fillna("")
            if s.empty:
                return None
            return as_float((s.isin(["CASH", "USD", "USDT", "USDC", "NONE"]).mean()) * 100.0)
    return None


def derive_btc_days_pct(df: pd.DataFrame) -> float | None:
    for col in [
        "portfolio_held_asset",
        "selected_coin",
        "symbol",
        "asset",
        "holding",
        "position",
        "leader",
        "tradable_governed_asset",
        "baseline_held_asset",
    ]:
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

    derived_cash_days_pct = derive_cash_days_pct(paper_df)
    metrics["cash_days_pct"] = maybe_pct_from_fraction(get_metric_from_row(summary_row, "cash_days_pct"))
    if metrics["cash_days_pct"] is None:
        metrics["cash_days_pct"] = derived_cash_days_pct
    elif derived_cash_days_pct is not None and abs(float(metrics["cash_days_pct"])) < 1e-12 and abs(float(derived_cash_days_pct)) > 1e-12:
        metrics["cash_days_pct"] = derived_cash_days_pct

    raw_btc = get_metric_from_row(summary_row, "btc_days_pct")
    if raw_btc is None:
        raw_btc = get_metric_from_row(summary_row, "btc_days")
    metrics["btc_days_pct"] = maybe_pct_from_fraction(raw_btc)
    derived_btc_days_pct = derive_btc_days_pct(paper_df)
    if metrics["btc_days_pct"] is None:
        metrics["btc_days_pct"] = derived_btc_days_pct
    elif derived_btc_days_pct is not None and abs(float(metrics["btc_days_pct"])) < 1e-12 and abs(float(derived_btc_days_pct)) > 1e-12:
        metrics["btc_days_pct"] = derived_btc_days_pct

    metrics["latest_date"] = None
    latest_date_candidates = []

    for date_key in ["latest_available_date", "strategy_last_closed_day", "last_closed_day", "latest_date"]:
        live_date = get_text_from_row(live_row, date_key)
        if live_date:
            parsed_live_date = pd.to_datetime(live_date, errors="coerce")
            if not pd.isna(parsed_live_date):
                latest_date_candidates.append(parsed_live_date.normalize())

    if not paper_df.empty:
        parsed_paper_date = pd.to_datetime(paper_df["ts"].iloc[-1], errors="coerce")
        if not pd.isna(parsed_paper_date):
            latest_date_candidates.append(parsed_paper_date.normalize())

    if latest_date_candidates:
        metrics["latest_date"] = max(latest_date_candidates).strftime("%Y-%m-%d")

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

def load_live_public_state(contract_cfg: dict, live_path: str | None, model_key: str, lang: str) -> dict:
    df = load_csv_optional(live_path)
    row = None
    if not df.empty:
        row_df = df.loc[df["model"] == model_key] if "model" in df.columns else pd.DataFrame()
        row = row_df.iloc[0] if not row_df.empty else df.iloc[0]

    required_cols = [
        "held_asset_public",
        "held_state_label",
        "execution_state",
    ]
    has_new_fields = row is not None and all(col in df.columns for col in required_cols)

    held_asset_public_raw = get_text_from_row(row, "held_asset_public") if has_new_fields else None
    held_state_label_raw = get_text_from_row(row, "held_state_label") if has_new_fields else None

    live_mode_contract = get_current_live_mode_contract(contract_cfg)

    live_truth_mode_raw = live_mode_contract.get("live_truth_mode")
    execution_profile_raw = live_mode_contract.get("execution_profile")
    fallback_profile_label_raw = live_mode_contract.get("fallback_profile_label")

    return {
        "has_new_fields": has_new_fields,
        "held_asset_public": prettify_asset_public(held_asset_public_raw, lang),
        "held_state_label": safe_text_value(held_state_label_raw, lang),
        "live_truth_mode": prettify_live_mode(live_truth_mode_raw, lang),
        "execution_profile": prettify_execution_profile(execution_profile_raw, lang),
        "fallback_profile_label": prettify_execution_profile(fallback_profile_label_raw, lang),
        "approval_gate_status": live_mode_contract.get("approval_gate_status"),
        "real_order_gate_status": live_mode_contract.get("real_order_gate_status"),
        "real_order_eligible_status": live_mode_contract.get("real_order_eligible_status"),
    }


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

    main_plot = filter_from_year(main_df, year)
    btc_plot = filter_from_year(btc_df, year)

    fig.add_trace(
        go.Scatter(
            x=main_plot["ts"],
            y=rebase_series(main_plot["equity"]),
            mode="lines",
            name=main_label,
            line=dict(width=4.8, color="#ff6b6b"),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=btc_plot["ts"],
            y=rebase_series(btc_plot["close"]),
            mode="lines",
            name=btc_label,
            line=dict(width=2.4, color="#60a5fa", dash="solid"),
        )
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
        xaxis_title="",
        yaxis_title="Indexed growth",
        hovermode="closest",
        xaxis=dict(showgrid=False, showspikes=True, spikemode="across", spikesnap="cursor"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
        hoverlabel=dict(
            bgcolor="rgba(10,15,24,0.96)",
            bordercolor="rgba(255,255,255,0.10)",
            font=dict(size=12),
        ),
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
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.015)",
        margin=dict(l=20, r=20, t=50, b=20),
        yaxis=dict(range=[-1.05, 1.05], gridcolor="rgba(255,255,255,0.06)"),
        xaxis=dict(showgrid=False),
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
# APP
# =========================================================

inject_css()

if "lang" not in st.session_state:
    st.session_state.lang = "sk"
if "execution_controls_notice" not in st.session_state:
    st.session_state.execution_controls_notice = ""
if "execution_bridge_result" not in st.session_state:
    st.session_state.execution_bridge_result = {}

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
labels = build_display_map(selector_cfg, lang)

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
        paper_df = load_model_paper(source_cfg.get("paper_dir"), model_key, explicit_paper_path=source_cfg.get("paper_path"))
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
live_public_state = load_live_public_state(selector_cfg, main_source.get("live_status_path"), main_key, lang)

trend_source_cfg = selector_cfg.get("trend_barometer_source", {}) or {}
trend_live = load_trend_barometer_live(trend_source_cfg, lang)
trend_history_df = load_trend_barometer_history(trend_source_cfg)
account_observability_cfg = get_current_account_observability_contract(selector_cfg)
account_status_payload = load_json_optional(account_observability_cfg.get("status_json_path"))
account_snapshot_payload = load_json_optional(account_observability_cfg.get("snapshot_json_path"))
account_snapshot_view = build_account_snapshot_view(account_status_payload, account_snapshot_payload)
runtime_health_payload = load_json_optional(DEFAULT_RUNTIME_HEALTH_PATH)
dry_run_decision_payload = load_json_optional(DEFAULT_DRY_RUN_DECISION_PATH)
real_order_gate_payload = load_json_optional(DEFAULT_REAL_ORDER_GATE_PATH)
execution_mode_payload = load_json_optional(EXECUTION_MODE_CONFIG_PATH)
live_order_policy_payload = load_json_optional(LIVE_ORDER_POLICY_PATH)
trading_operation_mode_payload = load_trading_operation_mode_payload(TRADING_OPERATION_MODE_CONFIG_PATH)
runtime_guardrail_payload = get_nested_dict(runtime_health_payload, "execution_mode_guardrail")
if not runtime_guardrail_payload:
    runtime_guardrail_payload = get_nested_dict(runtime_health_payload, "preflight_check", "execution_mode_guardrail")

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

    if home_cards:
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
        index=years.index(2025) if 2025 in years else 0,
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
        width="stretch",
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
        render_color_card(
            t(lang, "latest_date"),
            format_date_text(main_metrics.get("latest_date"), lang),
            "",
            METRIC_HELP[lang][t(lang, "latest_date")],
            "neutral",
        )

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
                t(lang, "calc_used_date"): format_date_text(used_date, lang),
                t(lang, "calc_value"): f"{value_now:,.2f} €",
                t(lang, "calc_return"): f"{ret_pct:+.2f}%",
            }
        ]
    )
    st.dataframe(calc_df, width="stretch", hide_index=True)
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
                "Dátum" if lang == "sk" else "Date": format_date_text(e_used, lang),
                "Hodnota" if lang == "sk" else "Value": f"{e_value:,.2f} €",
                "Zhodnotenie" if lang == "sk" else "Return": f"{e_ret:+.2f}%",
            }
        )

    st.markdown(f"#### {t(lang, 'quick_examples')}")
    st.dataframe(pd.DataFrame(example_rows), width="stretch", hide_index=True)

    st.markdown(f"### {t(lang, 'overview_title')}")
    st.markdown(t(lang, "overview_md"))

    if paper_errors:
        st.warning(" / ".join(paper_errors))

with tabs[1]:
    st.subheader(t(lang, "account_title"))
    st.caption(t(lang, "account_snapshot_note"))
    account_enabled = as_bool(account_observability_cfg.get("enabled"))

    if account_enabled is False:
        st.info(account_ui_text(lang, "observability_disabled"))
    else:
        bridge_result = st.session_state.get("execution_bridge_result") or {}
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
        live_block_reasons = list(live_gate_state["reasons"])
        operation_mode = str(trading_operation_mode_payload.get("mode") or "manual").strip().lower() or "manual"
        operation_mode_label = prettify_trading_operation_mode(operation_mode, lang)
        operation_mode_updated_at_text = format_utc_text(
            trading_operation_mode_payload.get("updated_at_utc"),
            lang,
        )
        operation_mode_updated_by = str(trading_operation_mode_payload.get("updated_by") or "").strip() or "system"
        operation_mode_fail_closed = bool(trading_operation_mode_payload.get("fail_closed", False))
        operation_mode_error = str(trading_operation_mode_payload.get("error") or "").strip()
        scheduler_mode_explanation = build_scheduler_mode_explanation(operation_mode, lang)
        safety_posture_label = build_safety_posture_label(execution_mode_payload, lang)
        safety_posture_detail = build_safety_posture_detail(execution_mode_payload, lang)
        signal_result_label = build_signal_result_label(dry_run_decision_payload, lang)
        signal_result_detail = build_signal_result_detail(dry_run_decision_payload, lang)
        gate_result_label = build_gate_result_label(real_order_gate_payload, lang)
        gate_result_detail = build_gate_result_detail(real_order_gate_payload, lang)

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
        refresh_timestamp = format_utc_text(account_snapshot_view.get("as_of_utc"), lang)
        dry_run_timestamp = format_utc_text(dry_run_decision_payload.get("generated_at_utc"), lang)
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
        sync_text = format_utc_text(account_snapshot_view.get("as_of_utc"), lang)
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

        if account_ui_text(lang, "proof_banner").strip():
            st.markdown(f"#### {account_ui_text(lang, 'proof_banner')}")
        render_ops_strip(
            [
                {
                    "label": account_ui_text(lang, "proof_state"),
                    "value": proof_state_text,
                },
                {
                    "label": account_ui_text(lang, "read_mode"),
                    "value": read_mode_text,
                },
                {
                    "label": account_ui_text(lang, "mode"),
                    "value": mode_text,
                },
            ],
            tone="proof",
        )
        if placeholder_framing:
            st.caption(placeholder_framing)
        if runtime_error_text != t(lang, "na"):
            friendly_runtime_error = friendly_hyperliquid_error_message(runtime_error_text, lang)
            st.warning(friendly_runtime_error or f"{account_ui_text(lang, 'runtime_error')}: {runtime_error_text}")

        st.markdown("#### Ovladanie")
        with st.container(border=True):
            st.markdown("**Rezim obchodovania**")
            render_ops_strip(
                [
                    {
                        "label": "Zvoleny runtime mod" if lang == "sk" else "Selected runtime mode",
                        "value": operation_mode_label,
                    },
                    {
                        "label": "Signal" if lang == "sk" else "Signal",
                        "value": signal_result_label,
                    },
                ],
                tone="proof",
            )

            mode_manual_col, mode_auto_col = st.columns(2)
            with mode_manual_col:
                if st.button(
                    "Manualne obchody",
                    key="execution_controls_set_manual_mode",
                    width="stretch",
                    disabled=(not bridge_available) or operation_mode == "manual",
                ):
                    result = run_app_execute_action(action="set_manual_mode")
                    st.session_state.execution_bridge_result = result
                    st.session_state.execution_controls_notice = build_execution_notice(result, lang)
                    st.rerun()
            with mode_auto_col:
                if st.button(
                    "Automaticke obchody",
                    key="execution_controls_set_automatic_mode",
                    width="stretch",
                    disabled=(not bridge_available) or operation_mode == "automatic",
                ):
                    result = run_app_execute_action(action="set_automatic_mode")
                    st.session_state.execution_bridge_result = result
                    st.session_state.execution_controls_notice = build_execution_notice(result, lang)
                    st.rerun()

            st.divider()
            st.markdown("**Jednorazove akcie uctu**")

            if not bridge_available:
                st.warning("Tieto akcie teraz nie sú dostupné.")

            refresh_col, dry_run_col, live_col = st.columns(3)

            with refresh_col:
                render_phase_badge("LEN NA CITANIE", "#365f9c")
                render_ops_inline_note(
                    "Zhrnutie",
                    f"Posledna aktualizacia: {refresh_timestamp}",
                )
                if refresh_missing_artifacts:
                    st.warning("Niektoré údaje o účte momentálne chýbajú.")
                if st.button(
                    "Obnovit udaje",
                    key="execution_controls_refresh",
                    width="stretch",
                    disabled=not bridge_available,
                ):
                    with st.spinner("Obnovujem realne operational/account artefakty..."):
                        result = run_app_execute_action(action="refresh")
                    st.session_state.execution_bridge_result = result
                    st.session_state.execution_controls_notice = build_execution_notice(result, lang)
                    st.rerun()
                if bridge_result.get("action") == "refresh":
                    st.caption(build_execution_notice(bridge_result, lang))

            with dry_run_col:
                render_phase_badge("SIGNAL", "#8a6d1f")
                render_ops_inline_note(
                    "Zhrnutie",
                    dry_run_summary_text,
                )
                if dry_run_missing_artifacts:
                    st.warning("Kontrola signálu teraz nemá všetky podklady.")
                if st.button(
                    "Skontrolovat signal",
                    key="execution_controls_recompute",
                    width="stretch",
                    disabled=not bridge_available,
                ):
                    with st.spinner("Kontrolujem dnesny signal bez odoslania obchodu..."):
                        result = run_app_execute_action(action="dry_run")
                    st.session_state.execution_bridge_result = result
                    st.session_state.execution_controls_notice = build_execution_notice(result, lang)
                    st.rerun()
                if bridge_result.get("action") == "dry_run":
                    st.caption(build_execution_notice(bridge_result, lang))

            with live_col:
                render_phase_badge("OBCHOD", "#8e3b3b")
                render_ops_inline_note(
                    "Zhrnutie",
                    "Obchod sa odošle len vtedy, keď ho systém dnes naozaj povolí.",
                )
                if live_block_reasons:
                    simple_blockers = [simplify_live_block_reason(item, lang) for item in live_block_reasons]
                    simple_blockers = [item for item in dict.fromkeys(simple_blockers) if item]
                    st.warning(build_live_blocked_notice(simple_blockers, lang))
                confirmation_input = st.text_input(
                    "Potvrdenie",
                    key="execution_controls_live_confirmation",
                    placeholder=LIVE_ORDER_CONFIRMATION_TEXT,
                    help="Ak chcete obchod odoslať, napíšte presne POTVRDZUJEM.",
                )
                confirmation_matches = confirmation_input.strip() == LIVE_ORDER_CONFIRMATION_TEXT
                if not confirmation_matches:
                    st.caption(f"Presny text: {LIVE_ORDER_CONFIRMATION_TEXT}")
                if st.button(
                    "Odoslat obchod",
                    key="execution_controls_execute",
                    width="stretch",
                    disabled=(not live_gate_state["ok"]) or (not confirmation_matches),
                    help="APP vola iba allowlistnuty bridge a ten dalej vola submit_controlled_real_order.py.",
                ):
                    with st.spinner("Spustam one-shot controlled submit backend path..."):
                        result = run_app_execute_action(
                            action="live_execute",
                            ui_confirmation_text=(
                                APP_UI_CONFIRMATION_TEXT
                                if confirmation_matches
                                else confirmation_input
                            ),
                            backend_confirm_token=APP_BACKEND_CONFIRM_TOKEN,
                        )
                    st.session_state.execution_bridge_result = result
                    st.session_state.execution_controls_notice = build_execution_notice(result, lang)
                    st.rerun()
                if bridge_result.get("action") == "live_execute":
                    st.caption(build_execution_notice(bridge_result, lang))

        st.markdown(f"#### {account_ui_text(lang, 'overview')}")
        render_ops_strip(
            [
                {
                    "label": t(lang, "account_connection"),
                    "value": connection_text if account_snapshot_view.get("status") else t(lang, "account_status_unavailable"),
                },
                {
                    "label": t(lang, "account_last_sync"),
                    "value": format_utc_text(account_snapshot_view.get("as_of_utc"), lang),
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

        dense_cols = st.columns([1.2, 1])
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

        if no_position:
            render_ops_detail_panel(
                t(lang, "account_position_details"),
                [(t(lang, "account_open_position"), t(lang, "account_no_position"))],
                tone="detail",
                note=t(lang, "account_position_empty_note"),
            )
        else:
            side_key = str(open_position.get("side")).upper()
            if side_key == "LONG":
                position_side_text = t(lang, "account_long")
            elif side_key == "SHORT":
                position_side_text = t(lang, "account_short")
            else:
                position_side_text = safe_text_value(open_position.get("side"), lang=lang)

            render_ops_detail_panel(
                t(lang, "account_position_details"),
                [
                    (t(lang, "account_symbol"), safe_text_value(open_position.get("symbol"), lang=lang)),
                    (t(lang, "account_side"), position_side_text),
                    (t(lang, "account_size"), safe_plain_number_text(open_position.get("size"), decimals=6, lang=lang)),
                    (t(lang, "account_entry_price"), safe_usd_text(open_position.get("entry_price"), decimals=2, lang=lang)),
                    (t(lang, "account_mark_price"), safe_usd_text(open_position.get("mark_price"), decimals=2, lang=lang)),
                    (t(lang, "account_unrealized_pnl_usd"), safe_signed_usd_text(open_position.get("unrealized_pnl_usd"), decimals=2, lang=lang)),
                    (t(lang, "account_unrealized_pnl_pct"), safe_signed_pct_text(open_position.get("unrealized_pnl_pct"), decimals=2, lang=lang)),
                ],
                tone="detail",
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
