#!/usr/bin/env python3
"""Apply the reviewed TrendAtlas status fix to the separate Pi kiosk checkout.

This patch changes only anchored spans. It never copies a sanitized development
snapshot onto the Pi, so local authentication and configuration stay intact.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


ORIGINAL_SHA256 = {
    "home_dashboard.py": "ed58df80c8f32028721bec092b34e04709a4d99f5d61aea723d2831a3d8c6331",
    "static/app.js": "d4509c7ce799734a7fc541c6454c813e622afbd316645e830abef03b8210b5c2",
}

PY_PATCHES = [
    (
        "from datetime import datetime, timezone\nfrom http import HTTPStatus",
        "from datetime import date, datetime, timedelta, timezone\nfrom http import HTTPStatus",
    ),
    (
        '''    target_exposure = safe_float(execution_intent.get("target_exposure") or latest.get("execution_target_exposure"), 0.0)''',
        '''    target_exposure = safe_float(execution_intent.get("target_exposure") if "target_exposure" in execution_intent else latest.get("execution_target_exposure"))''',
    ),
    (
        '''    real_is_cash = (str(target_asset or "").upper() == "CASH") or (target_exposure is not None and abs(target_exposure) < 1e-12)
    real_account_asset = "CASH" if real_is_cash else (target_asset or "n/a")
    real_account_exposure = 0.0 if real_is_cash else (target_exposure or 0.0)
    real_account_state = "Mimo trhu" if real_is_cash else "V trhu"
    trade_submission_state = "Blokované" if real_is_cash or safe_bool(health_summary.get("block_execution")) else "Pripravené"''',
        '''    # A strategy target is not a wallet position. Use only account evidence here.
    wallet_summary = (account_snapshot or {}).get("summary") or {}
    if wallet_summary.get("positions_count") == 0:
        real_account_asset = "CASH"
        real_account_exposure = 0.0
        real_account_state = "Mimo trhu"
    else:
        real_account_asset = "Nedostupné"
        real_account_exposure = None
        real_account_state = "Stav účtu nedostupný"''',
    ),
    (
        '''        trade_submission_state = "Pripravené" if safe_bool(runtime_real_account_state.get("would_place_real_order")) else "Blokované"
        target_asset = runtime_real_account_state.get("intent_target_asset") or target_asset''',
        '''        target_asset = runtime_real_account_state.get("intent_target_asset") or target_asset''',
    ),
    (
        '''    if str(target_asset or "").upper() == "CASH" or abs(float(target_exposure or 0.0)) < 1e-12 or gate_status == "blocked" or not would_place_real_order:
        real_account_asset = "CASH"
        real_account_exposure = 0.0
        real_account_state = "Mimo trhu"
        trade_submission_state = "Blokované"
    dashboard_contract = dashboard_public_status or {}''',
        '''    dashboard_contract = dashboard_public_status or {}''',
    ),
    (
        '''        trade_submission_state = "Pripravené" if safe_bool(dash_exec.get("would_place_real_order")) else "Blokované"

    if dash_model:''',
        '''
    if dash_model:''',
    ),
    (
        '''    live_market_state = dashboard_contract.get("live_market_state") or {}''',
        '''    effective_gate_status = str(dash_exec.get("gate_status") or gate_status).strip().lower()
    effective_would_place = dash_exec.get("would_place_real_order")
    if effective_would_place is None:
        effective_would_place = (real_order_gate_payload or {}).get("would_place_real_order")
    target_code = str(target_asset or "").upper()
    target_is_cash = target_code in {"CASH", "USD", "USDC", "USDT"} or (
        bool(target_code) and target_exposure is not None and abs(float(target_exposure)) < 1e-12
    )
    if effective_gate_status == "blocked" or (safe_bool(health_summary.get("block_execution")) and not target_is_cash):
        trade_submission_state = "Blokované"
        gate_reasons = dash_exec.get("block_reasons") or (real_order_gate_payload or {}).get("block_reasons") or []
        reason_labels = (
            ("stale", "Neaktuálny signál"),
            ("fresh", "Neaktuálne vstupné údaje"),
            ("data_health", "Neaktuálne vstupné údaje"),
            ("duplicate", "Riziko duplicitnej objednávky"),
            ("kill_switch", "Bezpečnostná poistka"),
            ("collateral", "Nedostatok voľných prostriedkov"),
            ("manual_approval", "Chýbajúce schválenie"),
        )
        known_reason = next(
            (label for reason in gate_reasons if isinstance(reason, str) for token, label in reason_labels if token in reason.lower()),
            None,
        )
        blocking_gate = (
            f"Bezpečnostná kontrola pozastavila obchod: {known_reason}."
            if known_reason else "Bezpečnostná kontrola pozastavila obchod; podrobný dôvod nie je dostupný."
        )
    elif effective_gate_status == "no_action" and target_is_cash:
        trade_submission_state = "Čaká na signál"
        blocking_gate = "Žiadna bezpečnostná blokácia; zatiaľ nevznikla objednávka."
    elif effective_would_place is True:
        trade_submission_state = "Pripravené"
        blocking_gate = "Obchod podlieha aktuálnym kontrolám."
    else:
        trade_submission_state = "Čaká na kontrolu"
        blocking_gate = "Stav obchodnej kontroly nie je potvrdený."

    candidate_waiting = bool(model_preferred_asset and str(model_preferred_asset).upper() != "CASH" and target_is_cash)
    signal_status = (
        f"Model preferuje {model_preferred_asset}, vstup však ešte nie je potvrdený."
        if candidate_waiting else "Platí aktuálny schválený cieľ stratégie."
    )
    wait_condition = ((snapshot or {}).get("provenance") or {}).get("wait_condition") or (diagnostics or {}).get("current_wait_condition") or {}
    wait_code = str(dash_exec.get("wait_reason_code") or wait_condition.get("code") or "").strip().lower()
    wait_reason = {
        "candidate_entry_not_authorized": "Model zatiaľ nepotvrdil vstup do trhu.",
        "early_risk_cooldown_block": "Po poslednej zmene ešte trvá čakacia lehota.",
        "cooldown_clearance_pending_for_candidate_entry": "Po poslednej zmene ešte trvá čakacia lehota.",
    }.get(wait_code)
    if not wait_reason:
        wait_reason = "Čaká sa na potvrdenie vstupných podmienok." if candidate_waiting else blocking_gate
    now_utc = datetime.now(timezone.utc)
    next_evaluation = now_utc.replace(hour=0, minute=10, second=0, microsecond=0)
    if now_utc >= next_evaluation:
        next_evaluation += timedelta(days=1)
    next_evaluation_utc = next_evaluation.strftime("%d.%m.%Y %H:%M UTC")
    next_rebalance_date = str(dash_exec.get("next_rebalance_date") or (snapshot or {}).get("next_rebalance_date") or "").strip()
    next_rebalance_review_utc = None
    try:
        rebalance_review = date.fromisoformat(next_rebalance_date) + timedelta(days=1)
        next_rebalance_review_utc = rebalance_review.strftime("%d.%m.%Y 00:10 UTC")
    except ValueError:
        pass

    live_market_state = dashboard_contract.get("live_market_state") or {}''',
    ),
    (
        '''        "trade_submission_state": trade_submission_state,
        "effective_market_exposure":''',
        '''        "trade_submission_state": trade_submission_state,
        "signal_status": signal_status,
        "wait_reason": wait_reason,
        "next_evaluation_utc": next_evaluation_utc,
        "next_rebalance_date": next_rebalance_date or None,
        "next_rebalance_review_utc": next_rebalance_review_utc,
        "blocking_gate": blocking_gate,
        "effective_market_exposure":''',
    ),
]

JS_PATCHES = [
    (
        '''  const realAsset = status.real_account_asset || status.target_asset || "CASH";
  const realExposure = formatExposure(status.real_account_exposure ?? status.target_exposure ?? 0) || "0.00x";
  const modelAsset = status.candidate_asset || status.current_asset || "--";
  const submitState = status.trade_submission_state || "Blokované";''',
        '''  const realAsset = status.real_account_asset || "Nedostupné";
  const realExposure = status.real_account_exposure == null
    ? "Nedostupné"
    : formatExposure(status.real_account_exposure) || "Nedostupné";
  const modelAsset = status.candidate_asset || "--";
  const submitState = status.trade_submission_state || "Čaká na kontrolu";''',
    ),
    (
        '''  $("strategyExplanation").textContent = `Reálny účet: ${realState} (${realAsset}, ${realExposure}). Model preferuje: ${modelAsset}. Výkon účtu používa canonical Hyperliquid PnL; vklady a výbery nie sú súčasťou PnL.`;''',
        '''  const reviewText = status.next_evaluation_utc
    ? `Najbližšia plánovaná kontrola: ${status.next_evaluation_utc}.`
    : "Čas ďalšej kontroly nie je dostupný.";
  const rebalanceText = status.next_rebalance_review_utc
    ? `Po ďalšom rebalance najskoršie vyhodnotenie ${status.next_rebalance_review_utc}; obchod závisí od potvrdeného signálu a kontrol.`
    : "";
  $("strategyExplanation").textContent = `Reálny účet: ${realState} (${realAsset}, ${realExposure}). ${status.signal_status || "Stav signálu nie je dostupný."} Dôvod čakania: ${status.wait_reason || "Nedostupný."} ${reviewText} ${rebalanceText} Bezpečnostná kontrola: ${status.blocking_gate || "Nedostupná."} Výkon účtu vychádza zo skutočných transakcií; vklady a výbery sa nepovažujú za zisk.`;''',
    ),
]


EXECUTION_PY_PATCHES = [
    (
        '    candidate_waiting = bool(model_preferred_asset and str(model_preferred_asset).upper() != "CASH" and target_is_cash)',
        '''    execution_result_state = dashboard_contract.get("execution_result_state") or {}
    model_target_state = dashboard_contract.get("model_target_state") or {}
    if real_account_asset == "MULTIPLE":
        real_account_asset = "Viac pozícií"
    last_execution_message = execution_result_state.get("public_message_sk") or "Výsledok posledného obchodného pokusu nie je dostupný."
    if execution_result_state.get("staying_cash") is True:
        trade_submission_state = "Zostáva mimo trhu"
        blocking_gate = last_execution_message
    elif execution_result_state.get("outcome"):
        blocking_gate = last_execution_message

    candidate_waiting = bool(model_preferred_asset and str(model_preferred_asset).upper() != "CASH" and target_is_cash)''',
    ),
    (
        '        "signal_status": signal_status,',
        '''        "last_execution_message": last_execution_message,
        "model_target_asset": model_target_state.get("asset"),
        "model_target_exposure": model_target_state.get("exposure_x"),
        "model_target_validated": model_target_state.get("validated") is True,
        "signal_status": signal_status,''',
    ),
]
EXECUTION_JS_PATCHES = [
    (
        '  $("strategyExplanation").textContent = `Reálny účet:',
        '''  const confirmedTarget = status.model_target_validated
    ? `Potvrdený cieľ: ${status.model_target_asset || "Nedostupný"}, ${formatExposure(status.model_target_exposure) || "Nedostupné"}.`
    : "Potvrdený cieľ nie je dostupný.";
  $("strategyExplanation").textContent = `${confirmedTarget} ${status.last_execution_message || ""} Reálny účet:''',
    ),
]


def build_execution_result_patch(python_raw: bytes, js_raw: bytes) -> tuple[bytes, bytes]:
    if b'"last_execution_message": last_execution_message' in python_raw:
        verify_installed_sources(python_raw, js_raw)
        return python_raw, js_raw
    verify_installed_sources(python_raw, js_raw)
    python_new = apply_anchors(python_raw, EXECUTION_PY_PATCHES)
    js_new = apply_anchors(js_raw, EXECUTION_JS_PATCHES)
    verify_installed_sources(python_new, js_new)
    return python_new, js_new


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_anchors(raw: bytes, patches: list[tuple[str, str]]) -> bytes:
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    for old, new in patches:
        old = old.replace("\n", newline)
        new = new.replace("\n", newline)
        if text.count(old) != 1:
            raise ValueError(f"Expected exactly one reviewed anchor; found {text.count(old)}")
        text = text.replace(old, new, 1)
    return text.encode("utf-8")


def build_patched_sources(python_raw: bytes, js_raw: bytes, *, verify_hash: bool = True) -> tuple[bytes, bytes]:
    if verify_hash:
        for name, raw in (("home_dashboard.py", python_raw), ("static/app.js", js_raw)):
            if sha256(raw) != ORIGINAL_SHA256[name]:
                raise ValueError(f"Unexpected {name} SHA256; patch aborted without writes")
    python_new = apply_anchors(python_raw, PY_PATCHES)
    js_new = apply_anchors(js_raw, JS_PATCHES)
    compile(python_new.decode("utf-8"), "home_dashboard.py", "exec")
    with tempfile.TemporaryDirectory() as folder:
        js_check = Path(folder) / "app.js"
        js_check.write_bytes(js_new)
        if not shutil.which("node"):
            raise RuntimeError("node --check is required before modifying kiosk JavaScript")
        subprocess.run(["node", "--check", str(js_check)], check=True, capture_output=True)
    return build_execution_result_patch(python_new, js_new)


def verify_installed_sources(python_raw: bytes, js_raw: bytes) -> None:
    checked_python, checked_js = python_raw, js_raw
    if b'"last_execution_message": last_execution_message' in python_raw:
        checked_python = apply_anchors(python_raw, [(new, old) for old, new in reversed(EXECUTION_PY_PATCHES)])
        checked_js = apply_anchors(js_raw, [(new, old) for old, new in reversed(EXECUTION_JS_PATCHES)])
    for raw, patches, name in (
        (checked_python, PY_PATCHES, "home_dashboard.py"),
        (checked_js, JS_PATCHES, "static/app.js"),
    ):
        text = raw.decode("utf-8").replace("\r\n", "\n")
        for old, new in patches:
            expected_old_count = 1 if old in new else 0
            if text.count(new) != 1 or text.count(old) != expected_old_count:
                raise ValueError(f"Incomplete or modified installed patch in {name}")
    compile(python_raw.decode("utf-8"), "home_dashboard.py", "exec")
    with tempfile.TemporaryDirectory() as folder:
        js_check = Path(folder) / "app.js"
        js_check.write_bytes(js_raw)
        subprocess.run(["node", "--check", str(js_check)], check=True, capture_output=True)


def atomic_preserving_write(path: Path, raw: bytes) -> None:
    original_stat = path.stat()
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, stat.S_IMODE(original_stat.st_mode))
        os.chown(temporary_name, original_stat.st_uid, original_stat.st_gid)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/home_automation"))
    parser.add_argument("--apply", action="store_true", help="Commit reviewed patch after preflight")
    args = parser.parse_args()
    paths = {
        "home_dashboard.py": args.root / "home_dashboard.py",
        "static/app.js": args.root / "static" / "app.js",
    }
    current = {name: path.read_bytes() for name, path in paths.items()}
    already = b'"next_rebalance_review_utc": next_rebalance_review_utc' in current["home_dashboard.py"] and b"const reviewText = status.next_evaluation_utc" in current["static/app.js"]
    if already:
        verify_installed_sources(current["home_dashboard.py"], current["static/app.js"])
        patched_py, patched_js = build_execution_result_patch(current["home_dashboard.py"], current["static/app.js"])
        if patched_py == current["home_dashboard.py"] and patched_js == current["static/app.js"]:
            print(f"ALREADY_APPLIED python_sha256={sha256(patched_py)} js_sha256={sha256(patched_js)}")
            return
    else:
        patched_py, patched_js = build_patched_sources(current["home_dashboard.py"], current["static/app.js"])
    print(f"CHECK_OK python_sha256={sha256(patched_py)} js_sha256={sha256(patched_js)}")
    if not args.apply:
        return
    backups = {}
    try:
        for name, path in paths.items():
            backup = path.with_name(path.name + ".trendatlas-before-execution-result.bak")
            if backup.exists():
                raise FileExistsError(f"Existing backup {backup}; inspect before continuing")
            shutil.copy2(path, backup)
            backups[name] = backup
        atomic_preserving_write(paths["home_dashboard.py"], patched_py)
        atomic_preserving_write(paths["static/app.js"], patched_js)
    except Exception:
        for name, path in paths.items():
            if name in backups and path.read_bytes() != current[name]:
                atomic_preserving_write(path, current[name])
        raise
    print("APPLIED; originals preserved in .trendatlas-before-execution-result.bak files")


if __name__ == "__main__":
    main()
