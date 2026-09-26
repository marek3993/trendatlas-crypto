"""Public model evidence collector. SFTP reads only; password is never persisted.

Remote source is fixed to the production repo. No service, API or refresh is run.
JSON metadata may be privacy-redacted; original and stored hashes are separate.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import zipfile

HERE = Path(__file__).resolve().parent
REMOTE_ROOT = "/opt/market_regime_v1"
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\b")
PRIVATE = re.compile(r"(?i)(private.?key|secret|password|credential|account_address|wallet_address|signer_address)")

def sha(data):
    return hashlib.sha256(data).hexdigest()

def sanitize(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if PRIVATE.search(k) else sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        return ADDRESS.sub("[REDACTED_ADDRESS]", value)
    return value

def safe_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name:
        raise ValueError("Unsafe relative path")
    if any(PRIVATE.search(part) or part == ".env" for part in p.parts):
        raise ValueError("Private source excluded")
    return p.as_posix()

def public_payload(name, payload):
    if name.endswith(".json"):
        obj = json.loads(payload)
        clean = sanitize(obj)
        if name.endswith(("production_run_manifest.json", "latest_production_run.json")):
            # Only model provenance and stage timestamps are needed. Account
            # balances, identifiers, order IDs and position sizes are excluded.
            keep = {"manifest_type", "run_id", "strategy_version", "target_closed_day",
                    "started_at", "finished_at", "final_status", "model_target_asset",
                    "model_target_exposure", "authority_status", "heavy_refresh_steps"}
            clean = {k: v for k, v in clean.items() if k in keep}
            clean["stages"] = {stage: {k: v for k, v in values.items()
                               if k in {"started_at", "finished_at", "status"}}
                               for stage, values in obj.get("stages", {}).items()}
        if clean != obj:
            return (json.dumps(clean, indent=2, sort_keys=True) + "\n").encode()
    if ADDRESS.search(payload.decode("utf-8", errors="replace")):
        raise ValueError("Account address in non-JSON input; excluded")
    if b"-----BEGIN" in payload and b"PRIVATE KEY-----" in payload:
        raise ValueError("Private material excluded")
    return payload

class Remote:
    def __init__(self, host, user):
        import paramiko
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        password = getpass.getpass("SSH password (not stored): ")
        self.client.connect(host, username=user, password=password, look_for_keys=False,
                            allow_agent=False, timeout=15)
        password = None
        self.sftp = self.client.open_sftp()

    def read(self, name):
        name = safe_path(name)
        path = REMOTE_ROOT + "/" + name
        before = self.sftp.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Source must be a regular file, not a symlink")
        with self.sftp.open(path, "rb") as handle:
            payload = handle.read()
        after = self.sftp.stat(path)
        if (before.st_mtime, before.st_size) != (after.st_mtime, after.st_size):
            raise ValueError("Source changed while read")
        return payload, before.st_mtime, before.st_atime

    def list(self, folder):
        try:
            return [folder + "/" + x.filename for x in self.sftp.listdir_attr(REMOTE_ROOT + "/" + folder)
                    if stat.S_ISREG(x.st_mode)]
        except FileNotFoundError:
            return []

    def walk(self, folder):
        result = []
        try:
            entries = self.sftp.listdir_attr(REMOTE_ROOT + "/" + folder)
        except FileNotFoundError:
            return result
        for entry in entries:
            name = folder + "/" + entry.filename
            if stat.S_ISDIR(entry.st_mode) and entry.filename != "__pycache__":
                result.extend(self.walk(name))
            elif stat.S_ISREG(entry.st_mode):
                result.append(name)
        return result

    def close(self):
        self.sftp.close()
        self.client.close()

def collect(remote, target, supplement=False):
    if target.exists():
        raise FileExistsError("Refusing to overwrite frozen evidence")
    folders = ["data/ohlcv", "data/ohlcv_phase67_top100", "data/ohlcv_4h", "data/funding", "data/macro",
               "outputs/production", "outputs/phase60_selective_restore_robustness",
               "outputs/phase63_btc_participation_overlay", "outputs/phase66g_production_candidate_live",
               "outputs/phase67j_final_narrow_validation_pack", "outputs/phase68g_portfolio_exposure_leverage_validation",
               "outputs/phase68g_portfolio_exposure_leverage_validation/papers",
               "outputs/execution/app_exports", "outputs/execution/freshness",
               "outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel",
               "outputs/execution/production_runs", "outputs/execution/authority"]
    names = {p for folder in folders for p in remote.list(folder) if p.endswith((".csv", ".json"))}
    names |= {"source_of_truth/project_truth.json", "source_of_truth/export_contract.json"}
    # Enumerate code actually supporting selection, performance and build lineage.
    root = HERE.parents[1]
    names |= {p.relative_to(root).as_posix() for p in (root / "scripts").glob("*.py")
              if p.name.startswith(("phase63_", "phase66e_", "phase66g_", "phase67j_", "phase68g_", "phase68h_", "dev_only_phase68g_", "dev_only_production_core_btc_", "approved_strategy_", "freshness_", "research_os_dev_only_bot_compare_common"))}
    names |= {p.relative_to(root).as_posix() for p in (root / "scripts/production").rglob("*.py")}
    names |= {p.relative_to(root).as_posix() for p in (root / "src/market_regime_v1").rglob("*.py")}
    names |= {"phase60_selective_restore_robustness.py", "scripts/__init__.py",
              "outputs/phase66b_governance_forensic/phase66b_governance_drop_candidates.csv"}
    if supplement:
        names = {p for folder in ["scripts/production", "outputs/execution/production_runs",
                                  "outputs/execution/tmp/publish_existing_validation/20260926_101707"]
                 for p in remote.walk(folder) if p.endswith((".py", ".json"))}
        names |= {"scripts/execution/run_trendatlas_production.py",
                  "scripts/execution/production_execution.py",
                  "scripts/execution/run_pi_authoritative_producer.py"}
    names = {p for p in names if not p.endswith(("execution_plan.json", "live_preflight.json"))}
    records, missing = {}, {}
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(names):
            try:
                payload, mtime, atime = remote.read(name)
                clean = public_payload(name, payload)
                info = zipfile.ZipInfo(name, time.gmtime(mtime)[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, clean)
                records[name] = {"sha256": sha(clean), "original_sha256": sha(payload),
                                 "redacted": clean != payload, "size": len(clean),
                                 "source_mtime_epoch": mtime, "source_atime_epoch": atime}
            except (OSError, ValueError) as exc:
                missing[name] = type(exc).__name__ + ": " + ADDRESS.sub("[REDACTED]", str(exc))
    manifest = {"schema_version": 1, "source": "Pi read-only SFTP /opt/market_regime_v1",
                "files": records, "unavailable": missing, "bundle_sha256": sha(target.read_bytes()),
                "capture_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "remote_operations": ["listdir", "lstat", "stat", "open_rb"],
                "remote_writes": False, "account_address_saved": False}
    target.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"files": len(records), "unavailable": missing, "bundle_sha256": manifest["bundle_sha256"]}))

def extract_verified(bundle, manifest, target):
    target = Path(target).resolve()
    if sha(Path(bundle).read_bytes()) != manifest["bundle_sha256"]:
        raise ValueError("Bundle SHA256 mismatch")
    with zipfile.ZipFile(bundle) as z:
        if len(z.namelist()) != len(set(z.namelist())) or set(z.namelist()) != set(manifest["files"]):
            raise ValueError("Bundle member mismatch")
        for name, meta in manifest["files"].items():
            safe_path(name)
            dest = (target/name).resolve()
            if not dest.is_relative_to(target):
                raise ValueError("Extraction escapes target")
            content = z.read(name)
            if sha(content) != meta["sha256"]:
                raise ValueError("Member SHA256 mismatch: " + name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            os.utime(dest, (meta["source_atime_epoch"], meta["source_mtime_epoch"]))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output", type=Path, default=HERE/"input_bundle.zip")
    parser.add_argument("--supplement", action="store_true")
    args = parser.parse_args()
    connection = Remote(args.host, args.user)
    try:
        collect(connection, args.output, args.supplement)
    finally:
        connection.close()
