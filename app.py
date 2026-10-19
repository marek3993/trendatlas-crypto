"""Public Clean 50/50 presentation. No legacy phase67j/68g or model-derived account data."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
from urllib.request import urlopen
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent

def _compute_average_annual_period_return_pct(series: pd.Series, dates: pd.Series) -> float:
    """Compatibility name; geometric CAGR over inclusive calendar days, never an arithmetic mean."""
    r = pd.to_numeric(series, errors="raise")
    d = pd.to_datetime(dates, errors="raise")
    if r.empty or r.isna().any() or (r <= -1).any() or d.isna().any():
        raise ValueError("Incomplete performance window")
    days = (d.max() - d.min()).days + 1
    return float(((1 + r).prod() ** (365.25 / days) - 1) * 100)

def load_public():
    names = ("clean5050_metrics.json", "clean5050_timeseries.csv", "signal.json")
    folder = os.environ.get("TRENDATLAS_CLEAN_PUBLIC_DIR")
    if folder:
        bodies = [(Path(folder) / n).read_bytes() for n in names]
    else:
        origin = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "https://figgfdxmlaawoqsgidyx.supabase.co")
        base = origin.rstrip("/") + "/storage/v1/object/public/trendatlas-clean-public"
        with urlopen(base + "/latest.json", timeout=10) as r:
            version = json.load(r)["version"]
        if len(version) != 64 or any(c not in "0123456789abcdef" for c in version):
            raise ValueError("Invalid publication")
        bodies = []
        for name in names:
            with urlopen(base + "/" + version + "/" + name, timeout=10) as r:
                bodies.append(r.read())
    m, signal = json.loads(bodies[0]), json.loads(bodies[2])
    frame = pd.read_csv(io.BytesIO(bodies[1]))
    if (m["schema_version"] != 1 or m["strategy_id"] != "trendatlas_clean_5050_v1"
        or m["window"]["start"] != "2021-01-01" or m["timeseries_sha256"] != hashlib.sha256(bodies[1]).hexdigest()
        or signal["strategy_id"] != m["strategy_id"] or signal["decision_closed_day_utc"] != m["window"]["end"]
        or len(frame) != m["window"]["days"] or frame.iloc[0]["date"] != m["window"]["start"]
        or frame.iloc[-1]["date"] != m["window"]["end"]):
        raise ValueError("Mismatched Clean publication")
    return m, frame, signal

def render():
    st.set_page_config(page_title="TrendAtlas Crypto — Clean 50/50", layout="wide")
    lang = st.radio("Language / Jazyk", ["sk", "en"], horizontal=True)
    t = json.loads((ROOT / "web/src/content/clean5050-copy.json").read_text())[lang]
    st.title(t["title"]); st.write(t["intro"])
    try:
        m, frame, signal = load_public()
    except Exception:
        st.info(t["unavailable"]); m = frame = signal = None
    fmt = lambda x: (f"{x:,.1f} %".replace(",", " ").replace(".", ",") if lang == "sk" else f"{x:,.1f}%") if x is not None else "—"
    st.subheader(t["performance"])
    if m:
        st.caption(t["dataThrough"] + " " + m["window"]["end"])
        a,b,c,d = st.columns(4)
        a.metric(t["cagr"], fmt(m["since_2021"]["cagr_pct"])); b.metric(t["drawdown"], fmt(m["since_2021"]["max_drawdown_pct"]))
        c.metric(t["sharpe"], str(round(m["since_2021"]["sharpe"], 2)) if m["since_2021"]["sharpe"] is not None else "—")
        d.metric(t["last12"], fmt(m["last_12_months"]["total_return_pct"]))
        d.caption(t["drawdown"] + " " + fmt(m["last_12_months"]["max_drawdown_pct"]) + " · BTC " + fmt(m["btc_last_12_months_pct"]))
    st.caption(t["note"])
    if m:
        st.subheader(t["model"] + ": " + " · ".join(f"{a} {fmt(w*100)}" for a,w in signal["ciel_vahy"].items()))
        st.caption(t["holding"] + " " + signal["drzat_pocas_dna_utc"])
        if signal["drzat_pocas_dna_utc"] != str(pd.Timestamp.now("UTC").date()): st.warning(t["stale"])
        fig = go.Figure()
        for label,column,color in [("Clean 50/50","clean_equity","#007e70"),(t["btc"],"btc_equity","#d49a33")]:
            fig.add_trace(go.Scatter(x=frame.date,y=frame[column],name=label,line={"color":color}))
        fig.update_layout(title=t["chart"],yaxis_type="log",hovermode="x unified")
        st.plotly_chart(fig,use_container_width=True)
        st.caption(t["assumptions"])
        st.caption(f'{t["fundingProxy"]}: {m["since_2021"]["funding_proxy_days"]}. {t["unpriced"]}: {m["since_2021"]["unpriced_execution_proxy_days"]}.')
        st.subheader(t["annual"])
        st.dataframe(pd.DataFrame([{t["year"]:str(r["year"])+(f' ({t["partial"]})' if r["partial_year"] else ""),"Clean 50/50":fmt(r["return_pct"]),t["btc"]:fmt(r["btc_return_pct"])} for r in m["annual"]]),hide_index=True)
    st.subheader(t["how"])
    for i,step in enumerate(t["steps"],1): st.write(f"{i}. {step}")
    st.subheader(t["expect"])
    if m: st.write(t["cash"] + ": " + fmt(m["cash_days_pct"]))
    st.write(t["cashHelp"]);st.write(t["weak"]);st.write(t["params"])
    st.subheader(t["live"]); st.write(t["liveHelp"])
    account_url=os.environ.get("TRENDATLAS_ACCOUNT_APP_URL", "https://trendatlas-accounts.vercel.app")
    if account_url: st.link_button(t["login"], account_url.rstrip("/")+"/dashboard")
    else: st.info("Účet nájdete po prihlásení v aplikácii TrendAtlas." if lang=="sk" else "Sign in to the TrendAtlas account application to view your account.")

if __name__ == "__main__":
    render()
