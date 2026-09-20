"""Build a tiny allowlisted pinned release from git objects, never production."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASE = "research_os/dev_only/evolution_worker/"
FILES = [
    BASE + p for p in ("__init__.py", "runtime.py", "bootstrap.py", "fixture.py", "gate.py", "CONTRACT.md",
                       "systemd/trendatlas-evolution-worker.service.in",
                       "systemd/trendatlas-evolution-dispatch.service.in",
                       "systemd/trendatlas-evolution-dispatch.timer")]
FILES += ["research_os/dev_only/mean_reversion/" + p for p in
          ("__init__.py", "__main__.py", "backtest.py", "controller.py", "CONTRACT.md", "study.json")]
FILES += ["research_os/dev_only/evolution/__init__.py", "research_os/dev_only/evolution/backtest.py"]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def build(destination, commit):
    revision = subprocess.check_output(["git", "rev-parse", commit + "^{commit}"], cwd=ROOT, text=True).strip()
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError("Release destination exists; no overwrite")
    destination.mkdir(parents=True)
    contents = {name: subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT) for name in FILES}
    release_path = "/opt/trendatlas-research/releases/" + revision
    for name in list(contents):
        if name.endswith(".in"):
            contents["units/" + Path(name).name[:-3]] = contents[name].replace(b"@RELEASE@", release_path.encode())
        elif name.endswith(".timer"):
            contents["units/" + Path(name).name] = contents[name]
    for name, raw in contents.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    identity = {"source_commit": revision, "files": {
        name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(contents.items())}}
    manifest = {**identity, "release_sha256": hashlib.sha256(canonical(identity).encode()).hexdigest()}
    (destination / "manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    archive = destination.with_suffix(".tar.gz")
    if archive.exists():
        raise ValueError("Archive exists")
    with tarfile.open(archive, "x:gz") as tar:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                info = tar.gettarinfo(str(path), arcname=path.relative_to(destination).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mode = 0o444
                info.mtime = 0
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
    return {"source_commit": revision, "release_sha256": manifest["release_sha256"],
            "release_path": release_path, "files": len(contents),
            "unpacked_bytes": sum(p.stat().st_size for p in destination.rglob("*") if p.is_file()),
            "archive_bytes": archive.stat().st_size, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "archive": str(archive)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args()
    print(json.dumps(build(args.destination, args.commit), indent=2))
