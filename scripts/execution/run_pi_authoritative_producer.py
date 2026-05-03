from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    validate_authoritative_dependency_closure,
)


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SCRIPT = ROOT / "scripts" / "daily_refresh_app_pipeline.py"
TERMINAL_ATTEMPT_STATUSES = frozenset({"success", "failed"})
CANONICAL_APP_EXPORT_PREFIX = ("outputs", "execution", "app_exports")
ALLOWED_SUPPORT_ARTIFACT_RELATIVE_PATHS = frozenset(
    {
        Path("outputs/execution/freshness/app_freshness_report.json").as_posix(),
    }
)
REMOTE_DRIFT_PUSH_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "[rejected]",
    "failed to push some refs",
)
AUTHORITY_GIT_USER_NAME_ENV = "MRV1_AUTHORITY_GIT_USER_NAME"
AUTHORITY_GIT_USER_EMAIL_ENV = "MRV1_AUTHORITY_GIT_USER_EMAIL"


def authority_repo_publish_context_from_env(
    env: Mapping[str, str] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, str]:
    source = os.environ if env is None else env
    resolved_root = Path(root) if root is not None else ROOT
    remote = str(source.get("MRV1_AUTHORITY_REPO_REMOTE") or "origin").strip()
    branch = str(source.get("MRV1_AUTHORITY_REPO_BRANCH") or "main").strip()
    publish_tree = str(
        source.get("MRV1_AUTHORITY_PUBLISH_TREE")
        or (resolved_root.parent / f"{resolved_root.name}__authority_publish")
    ).strip()
    max_push_attempts_raw = str(
        source.get("MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS") or "3"
    ).strip()
    if not remote:
        raise ValueError("MRV1_AUTHORITY_REPO_REMOTE must be non-empty")
    if not branch:
        raise ValueError("MRV1_AUTHORITY_REPO_BRANCH must be non-empty")
    if not publish_tree:
        raise ValueError("MRV1_AUTHORITY_PUBLISH_TREE must be non-empty")
    try:
        max_push_attempts = int(max_push_attempts_raw)
    except ValueError as exc:
        raise ValueError(
            "MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS must be an integer"
        ) from exc
    if max_push_attempts < 1:
        raise ValueError("MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS must be >= 1")
    return {
        "remote": remote,
        "branch": branch,
        "publish_tree": str(Path(publish_tree).expanduser().resolve()),
        "max_push_attempts": str(max_push_attempts),
    }


def load_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required authority artifact: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Authority artifact must be a JSON object: {path}")
    return payload


def _resolve_canonical_app_export_path(
    raw_path: Any,
    *,
    root: Path,
    field_name: str,
) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        raise ValueError(f"Missing required canonical app export path: {field_name}")
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_candidate = candidate.resolve()
    resolved_root = root.resolve()
    try:
        relative_path = resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"Canonical app export path must stay inside the runtime checkout: {field_name}={path_text}"
        ) from exc
    if relative_path.parts[: len(CANONICAL_APP_EXPORT_PREFIX)] != CANONICAL_APP_EXPORT_PREFIX:
        raise ValueError(
            "Canonical app export path must stay inside outputs/execution/app_exports: "
            f"{field_name}={path_text}"
        )
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(
            f"Missing required canonical app export artifact: {resolved_candidate}"
        )
    return resolved_candidate


def _resolve_canonical_support_artifact_path(
    raw_path: Any,
    *,
    root: Path,
    field_name: str,
) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        raise ValueError(f"Missing required canonical support artifact path: {field_name}")
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_candidate = candidate.resolve()
    resolved_root = root.resolve()
    try:
        relative_path = resolved_candidate.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Canonical support artifact path must stay inside the runtime checkout: {field_name}={path_text}"
        ) from exc
    if relative_path not in ALLOWED_SUPPORT_ARTIFACT_RELATIVE_PATHS:
        allowed_display = ", ".join(sorted(ALLOWED_SUPPORT_ARTIFACT_RELATIVE_PATHS))
        raise ValueError(
            "Canonical support artifact path is not allowlisted: "
            f"{field_name}={path_text} allowed={allowed_display}"
        )
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(
            f"Missing required canonical support artifact: {resolved_candidate}"
        )
    return resolved_candidate


def _resolve_required_app_publish_paths(
    latest_successful_snapshot_payload: Mapping[str, Any],
    *,
    root: Path,
) -> list[Path]:
    product_snapshot = latest_successful_snapshot_payload.get("app_product_snapshot")
    if not isinstance(product_snapshot, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing app_product_snapshot"
        )
    chart_source_paths = product_snapshot.get("chart_source_paths")
    if not isinstance(chart_source_paths, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing app_product_snapshot.chart_source_paths"
        )
    source_metadata = product_snapshot.get("source_metadata")
    if not isinstance(source_metadata, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing app_product_snapshot.source_metadata"
        )
    main_strategy_metrics_metadata = source_metadata.get("main_strategy_metrics")
    if not isinstance(main_strategy_metrics_metadata, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing "
            "app_product_snapshot.source_metadata.main_strategy_metrics"
        )
    current_strategy_contract = load_current_main_strategy_root_contract(root=root)
    dependency_closure = validate_authoritative_dependency_closure(
        product_snapshot,
        current_strategy_contract,
        root=root,
        context="Authority repo publish blocked:",
    )
    return [
        _resolve_canonical_app_export_path(
            main_strategy_metrics_metadata.get("path"),
            root=root,
            field_name="app_product_snapshot.source_metadata.main_strategy_metrics.path",
        ),
        _resolve_canonical_app_export_path(
            chart_source_paths.get("main_strategy"),
            root=root,
            field_name="app_product_snapshot.chart_source_paths.main_strategy",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["reference_paper_path"]),
            root=root,
            field_name="app_product_snapshot.chart_source_paths.reference_strategy",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["reference_live_status_path"]),
            root=root,
            field_name="app_export_contract.model_sources.reference_strategy.live_status_path",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["phase66g_live_status_path"]),
            root=root,
            field_name="app_product_snapshot.source_metadata.trend_barometer_summary.path",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["phase66g_trend_history_path"]),
            root=root,
            field_name="app_product_snapshot.trend_history_source_path",
        ),
        _resolve_canonical_support_artifact_path(
            str(dependency_closure["freshness_report_path"]),
            root=root,
            field_name="app_product_snapshot.source_metadata.freshness.path",
        ),
    ]


def resolve_authority_publish_paths(root: Path | None = None) -> list[Path]:
    resolved_root = Path(root) if root is not None else ROOT
    publish_paths = [resolved_root / "outputs" / "execution" / "authority" / "latest_attempt_status.json"]
    snapshot_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
    )
    if snapshot_path.exists():
        latest_successful_snapshot_payload = load_json_required(snapshot_path)
        publish_paths.append(snapshot_path)
        publish_paths.extend(
            _resolve_required_app_publish_paths(
                latest_successful_snapshot_payload,
                root=resolved_root,
            )
        )
    deduped_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for path in publish_paths:
        resolved_path = path.resolve()
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        deduped_paths.append(resolved_path)
    return deduped_paths


def _run_git_command(
    args: list[str],
    *,
    root: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        env=dict(os.environ if env is None else env),
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_git_ok(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    details = stderr or stdout or f"returncode={result.returncode}"
    raise RuntimeError(f"{label} failed: {details}")


def _is_remote_drift_push_failure(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    combined = "\n".join(
        part.strip() for part in ((result.stderr or ""), (result.stdout or "")) if part.strip()
    ).lower()
    return any(marker in combined for marker in REMOTE_DRIFT_PUSH_MARKERS)


def _ensure_publish_tree_is_external(runtime_root: Path, publish_tree: Path) -> None:
    resolved_runtime_root = runtime_root.resolve()
    resolved_publish_tree = publish_tree.resolve()
    if resolved_publish_tree == resolved_runtime_root:
        raise RuntimeError(
            "Authority publish tree must not be the runtime checkout root"
        )
    if resolved_runtime_root in resolved_publish_tree.parents:
        raise RuntimeError(
            "Authority publish tree must live outside the runtime checkout"
        )


def _resolve_git_remote_url(
    *,
    runtime_root: Path,
    remote: str,
    env: Mapping[str, str] | None = None,
) -> str:
    result = _run_git_command(
        ["remote", "get-url", remote],
        root=runtime_root,
        env=env,
    )
    _ensure_git_ok(result, label=f"git remote get-url {remote}")
    remote_url = (result.stdout or "").strip()
    if not remote_url:
        raise RuntimeError(f"git remote get-url {remote} returned an empty URL")
    return remote_url


def _resolve_authority_git_identity(
    *,
    runtime_root: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    source = os.environ if env is None else env
    configured_name = str(source.get(AUTHORITY_GIT_USER_NAME_ENV) or "").strip()
    configured_email = str(source.get(AUTHORITY_GIT_USER_EMAIL_ENV) or "").strip()

    if bool(configured_name) != bool(configured_email):
        raise RuntimeError(
            f"{AUTHORITY_GIT_USER_NAME_ENV} and {AUTHORITY_GIT_USER_EMAIL_ENV} must either both be set or both be unset"
        )
    if configured_name and configured_email:
        return configured_name, configured_email

    name_result = _run_git_command(
        ["config", "--get", "user.name"],
        root=runtime_root,
        env=env,
    )
    email_result = _run_git_command(
        ["config", "--get", "user.email"],
        root=runtime_root,
        env=env,
    )
    fallback_name = (name_result.stdout or "").strip() if name_result.returncode == 0 else ""
    fallback_email = (email_result.stdout or "").strip() if email_result.returncode == 0 else ""
    if fallback_name and fallback_email:
        return fallback_name, fallback_email

    raise RuntimeError(
        "Authority repo publish requires a git commit identity. "
        f"Set {AUTHORITY_GIT_USER_NAME_ENV}/{AUTHORITY_GIT_USER_EMAIL_ENV} "
        "or configure git user.name/user.email in the runtime checkout."
    )


def _build_git_publish_env(
    *,
    git_user_name: str,
    git_user_email: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    git_env = dict(os.environ if env is None else env)
    git_env["GIT_AUTHOR_NAME"] = git_user_name
    git_env["GIT_AUTHOR_EMAIL"] = git_user_email
    git_env["GIT_COMMITTER_NAME"] = git_user_name
    git_env["GIT_COMMITTER_EMAIL"] = git_user_email
    return git_env


def _clone_publish_tree(
    *,
    publish_tree: Path,
    remote: str,
    branch: str,
    remote_url: str,
    env: Mapping[str, str] | None = None,
) -> None:
    publish_tree.parent.mkdir(parents=True, exist_ok=True)
    clone_result = subprocess.run(
        [
            "git",
            "clone",
            "--origin",
            remote,
            "--branch",
            branch,
            "--single-branch",
            remote_url,
            str(publish_tree),
        ],
        cwd=str(publish_tree.parent),
        env=dict(os.environ if env is None else env),
        text=True,
        capture_output=True,
        check=False,
    )
    _ensure_git_ok(clone_result, label="git clone authority publish tree")


def _ensure_publish_tree_remote(
    *,
    publish_tree: Path,
    remote: str,
    remote_url: str,
    env: Mapping[str, str] | None = None,
) -> None:
    get_url_result = _run_git_command(
        ["remote", "get-url", remote],
        root=publish_tree,
        env=env,
    )
    if get_url_result.returncode == 0:
        current_remote_url = (get_url_result.stdout or "").strip()
        if current_remote_url != remote_url:
            set_url_result = _run_git_command(
                ["remote", "set-url", remote, remote_url],
                root=publish_tree,
                env=env,
            )
            _ensure_git_ok(set_url_result, label=f"git remote set-url {remote}")
        return

    add_remote_result = _run_git_command(
        ["remote", "add", remote, remote_url],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(add_remote_result, label=f"git remote add {remote}")


def _ensure_clean_publish_tree(
    *,
    runtime_root: Path,
    publish_tree: Path,
    remote: str,
    branch: str,
    remote_url: str,
    env: Mapping[str, str] | None = None,
) -> None:
    _ensure_publish_tree_is_external(runtime_root, publish_tree)
    if publish_tree.exists() and not (publish_tree / ".git").exists():
        raise RuntimeError(
            f"Authority publish tree exists but is not a git clone: {publish_tree}"
        )
    if not publish_tree.exists():
        _clone_publish_tree(
            publish_tree=publish_tree,
            remote=remote,
            branch=branch,
            remote_url=remote_url,
            env=env,
        )

    _ensure_publish_tree_remote(
        publish_tree=publish_tree,
        remote=remote,
        remote_url=remote_url,
        env=env,
    )

    fetch_result = _run_git_command(
        ["fetch", remote, branch],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(fetch_result, label="git fetch authority publish branch")

    checkout_result = _run_git_command(
        ["checkout", "-B", branch, f"{remote}/{branch}"],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(checkout_result, label="git checkout authority publish branch")

    reset_result = _run_git_command(
        ["reset", "--hard", f"{remote}/{branch}"],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(reset_result, label="git reset authority publish branch")

    clean_result = _run_git_command(
        ["clean", "-fd"],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(clean_result, label="git clean authority publish tree")


def _copy_publish_paths(
    *,
    runtime_root: Path,
    publish_tree: Path,
    publish_paths: list[Path],
) -> list[str]:
    pathspecs: list[str] = []
    for source_path in publish_paths:
        relative_path = source_path.relative_to(runtime_root)
        destination_path = publish_tree / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        pathspecs.append(relative_path.as_posix())
    return pathspecs


def build_authority_publish_commit_message(attempt_payload: Mapping[str, Any]) -> str:
    attempt_status = str(
        attempt_payload.get("latest_authoritative_attempt_status") or "unknown"
    ).strip().lower()
    target_closed_day = str(
        attempt_payload.get("target_closed_day_utc") or "unknown_day"
    ).strip()
    run_id = str(attempt_payload.get("run_id") or "unknown_run").strip()
    return f"Publish Pi authority artifacts: {attempt_status} {target_closed_day} {run_id}"


def publish_authority_artifacts_to_repo(
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    resolved_root = Path(root) if root is not None else ROOT
    latest_attempt_status_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
    )
    latest_successful_snapshot_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
    )
    context = authority_repo_publish_context_from_env(env, root=resolved_root)
    attempt_payload = load_json_required(latest_attempt_status_path)
    attempt_status = str(
        attempt_payload.get("latest_authoritative_attempt_status") or ""
    ).strip().lower()
    automatic_producer_id = str(attempt_payload.get("automatic_producer_id") or "").strip().lower()
    authority_role = str(attempt_payload.get("authority_role") or "").strip().lower()

    if attempt_status not in TERMINAL_ATTEMPT_STATUSES:
        raise RuntimeError(
            "Authority repo publish requires a terminal latest_attempt_status payload"
        )
    if automatic_producer_id != "raspberry_pi":
        raise RuntimeError(
            "Authority repo publish requires automatic_producer_id=raspberry_pi"
        )
    if authority_role != "pi_only_authoritative_producer":
        raise RuntimeError(
            "Authority repo publish requires authority_role=pi_only_authoritative_producer"
        )
    if attempt_status == "success" and not latest_successful_snapshot_path.exists():
        raise FileNotFoundError(
            "Successful authority publish requires snapshot artifact: "
            f"{latest_successful_snapshot_path}"
        )

    publish_paths = resolve_authority_publish_paths(resolved_root)
    if not publish_paths:
        raise RuntimeError("No authority artifacts available for repo publish")
    remote = context["remote"]
    branch = context["branch"]
    publish_tree = Path(context["publish_tree"])
    max_push_attempts = int(context["max_push_attempts"])
    git_user_name, git_user_email = _resolve_authority_git_identity(
        runtime_root=resolved_root,
        env=env,
    )
    git_env = _build_git_publish_env(
        git_user_name=git_user_name,
        git_user_email=git_user_email,
        env=env,
    )
    remote_url = _resolve_git_remote_url(
        runtime_root=resolved_root,
        remote=remote,
        env=git_env,
    )
    commit_message = build_authority_publish_commit_message(attempt_payload)
    pathspecs: list[str] = []
    for push_attempt in range(1, max_push_attempts + 1):
        _ensure_clean_publish_tree(
            runtime_root=resolved_root,
            publish_tree=publish_tree,
            remote=remote,
            branch=branch,
            remote_url=remote_url,
            env=git_env,
        )
        pathspecs = _copy_publish_paths(
            runtime_root=resolved_root,
            publish_tree=publish_tree,
            publish_paths=publish_paths,
        )
        add_result = _run_git_command(
            ["add", "--", *pathspecs],
            root=publish_tree,
            env=git_env,
        )
        _ensure_git_ok(add_result, label="git add authority artifacts")

        diff_result = _run_git_command(
            ["diff", "--cached", "--quiet", "--", *pathspecs],
            root=publish_tree,
            env=git_env,
        )
        if diff_result.returncode == 0:
            return {
                "published": False,
                "reason": "no_authority_repo_changes",
                "attempt_status": attempt_status,
                "remote": remote,
                "branch": branch,
                "remote_url": remote_url,
                "publish_tree": str(publish_tree),
                "push_attempts": push_attempt,
                "pathspecs": pathspecs,
                "commit_message": None,
            }
        if diff_result.returncode != 1:
            _ensure_git_ok(diff_result, label="git diff --cached authority artifacts")

        commit_result = _run_git_command(
            ["commit", "--only", "-m", commit_message, "--", *pathspecs],
            root=publish_tree,
            env=git_env,
        )
        _ensure_git_ok(commit_result, label="git commit authority artifacts")

        push_result = _run_git_command(
            ["push", remote, f"HEAD:{branch}"],
            root=publish_tree,
            env=git_env,
        )
        if push_result.returncode == 0:
            break
        if push_attempt < max_push_attempts and _is_remote_drift_push_failure(push_result):
            continue
        _ensure_git_ok(push_result, label="git push authority artifacts")

    head_result = _run_git_command(["rev-parse", "HEAD"], root=publish_tree, env=git_env)
    _ensure_git_ok(head_result, label="git rev-parse HEAD")
    commit_sha = (head_result.stdout or "").strip()

    return {
        "published": True,
        "reason": None,
        "attempt_status": attempt_status,
        "remote": remote,
        "branch": branch,
        "remote_url": remote_url,
        "publish_tree": str(publish_tree),
        "push_attempts": push_attempt,
        "pathspecs": pathspecs,
        "commit_message": commit_message,
        "commit_sha": commit_sha,
    }


def build_pi_authoritative_env() -> dict[str, str]:
    env = os.environ.copy()
    env["MRV1_ENABLE_AUTHORITY_PUBLISH"] = "1"
    env["MRV1_AUTHORITY_MODE"] = "authoritative"
    env["MRV1_AUTOMATIC_PRODUCER_ID"] = "raspberry_pi"
    env["MRV1_REQUIRE_PI_RUNTIME"] = "1"
    env.setdefault("MRV1_PUBLISH_HOSTNAME", socket.gethostname())
    env.setdefault("MRV1_AUTHORITY_REPO_REMOTE", "origin")
    env.setdefault("MRV1_AUTHORITY_REPO_BRANCH", "main")
    env.setdefault(
        "MRV1_AUTHORITY_PUBLISH_TREE",
        str(ROOT.parent / f"{ROOT.name}__authority_publish"),
    )
    env.setdefault("MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS", "3")
    env["MRV1_AUTHORITY_ENTRYPOINT"] = str(Path(__file__).resolve())
    return env


def main() -> None:
    if not PIPELINE_SCRIPT.exists():
        raise FileNotFoundError(f"Missing pipeline script: {PIPELINE_SCRIPT}")

    command = [sys.executable, str(PIPELINE_SCRIPT), *sys.argv[1:]]
    pi_env = build_pi_authoritative_env()
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        env=pi_env,
        check=False,
    )
    publish_result = publish_authority_artifacts_to_repo(
        root=ROOT,
        env=pi_env,
    )
    print(
        json.dumps(
            {
                "authority_repo_publish": publish_result,
            },
            indent=2,
            ensure_ascii=False,
        ),
        flush=True,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
