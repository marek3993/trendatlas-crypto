from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from services.pi.job_queue import build_queue
from services.shared.schemas import RuntimeConfig


DEFAULT_REQUIRED_ENV_VARS = (
    "RESEARCH_OS_ROOT",
)
_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RuntimeBootstrapError(RuntimeError):
    pass


def resolve_project_root(*, require_env: bool) -> Path:
    raw_root = os.environ.get("RESEARCH_OS_ROOT", "").strip()
    if raw_root:
        root = Path(raw_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise RuntimeBootstrapError(f"RESEARCH_OS_ROOT is not a valid directory: {root}")
        return root
    if require_env:
        raise RuntimeBootstrapError("RESEARCH_OS_ROOT is required but not set")
    return _DEFAULT_PROJECT_ROOT


def resolve_project_path(path: str | Path, project_root: Path) -> Path:
    raw = Path(path)
    return raw.resolve() if raw.is_absolute() else (project_root / raw).resolve()


def _normalize_openai_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["api_key_env"] = str(normalized.get("api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY")
    normalized["api_key_present"] = bool(os.environ.get(normalized["api_key_env"], "").strip())
    normalized["strict_schema_validation"] = bool(normalized.get("strict_schema_validation", True))
    normalized["fail_closed"] = bool(normalized.get("fail_closed", True))
    return normalized


def planner_component_config(config: RuntimeConfig) -> dict[str, Any]:
    planner = dict(config.planner or {})
    planner.setdefault("enabled", True)
    planner.setdefault("output_dir", "planner_outputs")
    planner["openai"] = _normalize_openai_payload(dict(planner.get("openai") or config.openai))
    return planner


def planner_openai_config(config: RuntimeConfig) -> dict[str, Any]:
    return dict(planner_component_config(config)["openai"])


def critic_component_config(config: RuntimeConfig) -> dict[str, Any]:
    critic = dict(config.critic or {})
    critic.setdefault("enabled", True)
    critic.setdefault("output_dir", "critic_outputs")
    critic["openai"] = _normalize_openai_payload(dict(critic.get("openai") or {}))
    return critic


def critic_openai_config(config: RuntimeConfig) -> dict[str, Any]:
    return dict(critic_component_config(config)["openai"])


def load_runtime_config(path: str | Path, *, require_root_env: bool = False) -> RuntimeConfig:
    project_root = resolve_project_root(require_env=require_root_env)
    config_path = resolve_project_path(path, project_root)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeBootstrapError(f"runtime config must be a JSON object: {config_path}")

    payload["registry_path"] = str(resolve_project_path(str(payload["registry_path"]), project_root))
    payload["artifact_root"] = str(resolve_project_path(str(payload["artifact_root"]), project_root))
    payload["runtime_root"] = str(resolve_project_path(str(payload["runtime_root"]), project_root))
    payload["required_env_vars"] = list(payload.get("required_env_vars", DEFAULT_REQUIRED_ENV_VARS))

    env_redis_url = os.environ.get("REDIS_URL", "").strip()
    if env_redis_url:
        payload["redis_url"] = env_redis_url

    planner_payload = dict(payload.get("planner", {}))
    planner_payload.setdefault("enabled", True)
    planner_payload.setdefault("output_dir", "planner_outputs")
    planner_payload["openai"] = _normalize_openai_payload(dict(planner_payload.get("openai") or payload.get("openai", {})))
    payload["planner"] = planner_payload

    critic_payload = dict(payload.get("critic", {}))
    critic_payload.setdefault("enabled", True)
    critic_payload.setdefault("output_dir", "critic_outputs")
    critic_payload["openai"] = _normalize_openai_payload(dict(critic_payload.get("openai") or {}))
    payload["critic"] = critic_payload

    payload["openai"] = dict(planner_payload["openai"])

    return RuntimeConfig.from_mapping(payload)


def _queue_consumer_streams(config: RuntimeConfig, role: str) -> list[str]:
    if role == "pc_worker":
        return [
            config.streams["heavy_validation_jobs"],
            config.streams["worker_jobs"],
        ]
    if role == "pi_orchestrator":
        return [config.streams["worker_results"]]
    return []


def _iter_required_api_key_envs(config: RuntimeConfig) -> list[str]:
    env_names: list[str] = []
    for openai_config in (planner_openai_config(config), critic_openai_config(config)):
        if bool(openai_config.get("enabled", False)):
            env_name = str(openai_config.get("api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY")
            if env_name not in env_names:
                env_names.append(env_name)
    return env_names


def _runtime_env_checks(config: RuntimeConfig, *, require_root_env: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required_envs = list(config.required_env_vars or DEFAULT_REQUIRED_ENV_VARS)
    queue_backend = config.queue_backend.strip().lower().replace("-", "_")
    api_key_envs = set(_iter_required_api_key_envs(config))
    reserved_envs = {"RESEARCH_OS_ROOT", "REDIS_URL", *api_key_envs}

    root_value = os.environ.get("RESEARCH_OS_ROOT", "").strip()
    if require_root_env:
        checks.append(
            {
                "name": "env:RESEARCH_OS_ROOT",
                "ok": bool(root_value),
                "detail": str(Path(root_value).expanduser()) if root_value else "missing",
            }
        )
    else:
        checks.append(
            {
                "name": "env:RESEARCH_OS_ROOT",
                "ok": True,
                "detail": str(Path(root_value).expanduser()) if root_value else "optional; using repo default when unset",
            }
        )

    if queue_backend in {"redis", "redis_streams"}:
        redis_env = os.environ.get("REDIS_URL", "").strip()
        redis_url = redis_env or config.redis_url.strip()
        checks.append(
            {
                "name": "redis_url",
                "ok": bool(redis_url),
                "detail": redis_url if redis_url else "missing",
            }
        )

    for env_name in _iter_required_api_key_envs(config):
        value = os.environ.get(env_name, "").strip()
        checks.append(
            {
                "name": f"env:{env_name}",
                "ok": bool(value),
                "detail": "present" if value else "missing",
            }
        )

    for env_name in required_envs:
        if env_name in reserved_envs:
            continue
        value = os.environ.get(env_name, "").strip()
        checks.append(
            {
                "name": f"env:{env_name}",
                "ok": bool(value),
                "detail": "present" if value else "missing",
            }
        )
    return checks


def collect_runtime_readiness(
    config: RuntimeConfig,
    *,
    config_path: str | Path,
    role: str,
    require_root_env: bool,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    project_root: Path | None = None
    try:
        project_root = resolve_project_root(require_env=require_root_env)
        checks.append({"name": "research_os_root", "ok": True, "detail": str(project_root)})
    except Exception as exc:
        checks.append({"name": "research_os_root", "ok": False, "detail": str(exc)})

    checks.extend(_runtime_env_checks(config, require_root_env=require_root_env))

    if project_root is None:
        project_root = _DEFAULT_PROJECT_ROOT

    resolved_config_path = resolve_project_path(config_path, project_root)
    checks.extend(
        [
            {"name": "config_path", "ok": resolved_config_path.exists(), "detail": str(resolved_config_path)},
            {"name": "artifact_root", "ok": Path(config.artifact_root).is_absolute(), "detail": config.artifact_root},
            {"name": "runtime_root", "ok": Path(config.runtime_root).is_absolute(), "detail": config.runtime_root},
            {"name": "registry_parent", "ok": Path(config.registry_path).parent.exists(), "detail": str(Path(config.registry_path).parent)},
        ]
    )

    queue_backend = config.queue_backend.strip().lower().replace("-", "_")
    if queue_backend in {"redis", "redis_streams"}:
        try:
            queue = build_queue(config.queue_backend, config.redis_url)
            if hasattr(queue, "ping"):
                queue.ping()
            checks.append({"name": "redis_ping", "ok": True, "detail": config.redis_url})
            for stream in _queue_consumer_streams(config, role):
                if hasattr(queue, "prepare_consumer_group"):
                    queue.prepare_consumer_group(stream, config.consumer_group)
                checks.append(
                    {
                        "name": f"redis_consumer_group:{stream}",
                        "ok": True,
                        "detail": f"group={config.consumer_group}",
                    }
                )
        except Exception as exc:
            checks.append({"name": "redis_ping", "ok": False, "detail": str(exc)})
    else:
        checks.append({"name": "redis_ping", "ok": True, "detail": f"queue_backend={config.queue_backend}; redis not required"})

    ok = all(bool(check["ok"]) for check in checks)
    return {
        "role": role,
        "ok": ok,
        "project_root": str(project_root),
        "config_path": str(resolved_config_path),
        "queue_backend": config.queue_backend,
        "registry_path": config.registry_path,
        "artifact_root": config.artifact_root,
        "runtime_root": config.runtime_root,
        "consumer_group": config.consumer_group,
        "consumer_name": config.consumer_name,
        "checks": checks,
    }


def assert_runtime_startup_ready(
    config: RuntimeConfig,
    *,
    config_path: str | Path,
    role: str,
    require_root_env: bool = True,
) -> dict[str, Any]:
    readiness = collect_runtime_readiness(
        config,
        config_path=config_path,
        role=role,
        require_root_env=require_root_env,
    )
    failures = [check for check in readiness["checks"] if not check["ok"]]
    if failures:
        formatted = "; ".join(f"{item['name']}={item['detail']}" for item in failures)
        raise RuntimeBootstrapError(f"{role} startup readiness failed: {formatted}")
    return readiness


def summarize_registry_status(registry: Any, *, include_jobs: int = 5) -> dict[str, Any]:
    return {
        "jobs": registry.list_jobs(limit=include_jobs),
        "family_state": registry.list_family_states(limit=include_jobs),
        "family_governor_state": registry.list_family_governor_states(limit=include_jobs),
        "heavy_validation_requests": registry.list_heavy_validation_requests(limit=include_jobs),
        "heavy_validation_results": registry.list_heavy_validation_results(limit=include_jobs),
        "family_verdicts": registry.list_family_verdicts(limit=include_jobs),
    }


def build_service_status(
    *,
    service_name: str,
    role: str,
    config: RuntimeConfig,
    config_path: str | Path,
    registry: Any,
    require_root_env: bool,
) -> dict[str, Any]:
    readiness = collect_runtime_readiness(
        config,
        config_path=config_path,
        role=role,
        require_root_env=require_root_env,
    )
    return {
        "service": service_name,
        "role": role,
        "status": "ok" if readiness["ok"] else "degraded",
        "readiness": readiness,
        "registry": summarize_registry_status(registry),
    }
