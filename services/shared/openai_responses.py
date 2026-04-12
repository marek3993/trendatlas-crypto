from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib import error, request


DEFAULT_RESPONSES_API_URL = "https://api.openai.com/v1/responses"


class OpenAIResponsesError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code,
            "error_message": str(self),
            "error_details": dict(self.details),
        }


@dataclass(frozen=True)
class StructuredResponseResult:
    response_id: str
    model: str
    status: str
    parsed: dict[str, Any]
    output_text: str
    usage: dict[str, Any]


def describe_openai_operation(openai_config: Mapping[str, Any]) -> dict[str, Any]:
    api_key_env = str(openai_config.get("api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY")
    api_key_present = bool(os.environ.get(api_key_env, "").strip())
    enabled = bool(openai_config.get("enabled", False))
    network_call = "disabled_by_config"
    if enabled and not api_key_present:
        network_call = "disabled_missing_api_key"
    elif enabled and api_key_present:
        network_call = "ready"
    return {
        "enabled": enabled,
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "model": str(openai_config.get("model", "")),
        "prompt_template": str(openai_config.get("prompt_template", "")),
        "responses_api": str(openai_config.get("responses_api", DEFAULT_RESPONSES_API_URL)),
        "reasoning_effort": str(openai_config.get("reasoning_effort", "")),
        "reasoning_summary": str(openai_config.get("reasoning_summary", "")),
        "timeout_seconds": int(openai_config.get("timeout_seconds", 60) or 60),
        "strict_schema_validation": bool(openai_config.get("strict_schema_validation", True)),
        "fail_closed": bool(openai_config.get("fail_closed", True)),
        "network_call": network_call,
    }


def serialize_openai_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, OpenAIResponsesError):
        return exc.to_dict()
    return {
        "error_code": "unexpected_openai_error",
        "error_message": str(exc),
        "error_details": {},
    }


def can_call_openai(openai_config: Mapping[str, Any]) -> bool:
    status = describe_openai_operation(openai_config)
    return bool(status["enabled"]) and bool(status["api_key_present"])


def _bootstrap_openai_operation(openai_config: Mapping[str, Any]) -> dict[str, Any]:
    status = describe_openai_operation(openai_config)
    if not bool(status["enabled"]):
        raise OpenAIResponsesError("disabled_by_config", "OpenAI Responses API is disabled by config")
    missing_fields = [
        field_name
        for field_name in ("model", "prompt_template", "responses_api")
        if not str(status.get(field_name, "")).strip()
    ]
    if missing_fields:
        raise OpenAIResponsesError(
            "bootstrap_config_error",
            f"OpenAI config missing required fields: {missing_fields}",
            details={"missing_fields": missing_fields},
        )
    if int(status["timeout_seconds"]) <= 0:
        raise OpenAIResponsesError("bootstrap_config_error", "OpenAI timeout_seconds must be > 0")
    if not str(status["responses_api"]).startswith("http"):
        raise OpenAIResponsesError(
            "bootstrap_config_error",
            "OpenAI responses_api must be an absolute http(s) URL",
            details={"responses_api": str(status["responses_api"])},
        )
    if not bool(status["api_key_present"]):
        raise OpenAIResponsesError(
            "missing_api_key",
            f"required API key is missing from {status['api_key_env']}",
            details={"api_key_env": status["api_key_env"]},
        )
    return status


def _raise_schema_error(code: str, message: str, *, schema_name: str, path: str, details: Mapping[str, Any] | None = None) -> None:
    payload = {"schema_name": schema_name, "path": path}
    payload.update(dict(details or {}))
    raise OpenAIResponsesError(code, message, details=payload)


def _validate_json_schema(schema_name: str, schema: Mapping[str, Any], value: Any, *, path: str = "$") -> None:
    schema_type = str(schema.get("type", "")).strip()
    if schema_type == "object":
        if not isinstance(value, Mapping):
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} expected object at {path}",
                schema_name=schema_name,
                path=path,
                details={"expected_type": "object", "actual_type": type(value).__name__},
            )
        required = [str(item) for item in list(schema.get("required", []))]
        missing = [key for key in required if key not in value]
        if missing:
            _raise_schema_error(
                "missing_required_key",
                f"{schema_name} missing required keys at {path}: {missing}",
                schema_name=schema_name,
                path=path,
                details={"missing_keys": missing},
            )
        properties = dict(schema.get("properties", {}) or {})
        if schema.get("additionalProperties", True) is False:
            extras = sorted(str(key) for key in value.keys() if key not in properties)
            if extras:
                _raise_schema_error(
                    "malformed_output",
                    f"{schema_name} has unexpected keys at {path}: {extras}",
                    schema_name=schema_name,
                    path=path,
                    details={"unexpected_keys": extras},
                )
        for key, child_schema in properties.items():
            if key in value:
                _validate_json_schema(schema_name, dict(child_schema), value[key], path=f"{path}.{key}")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} expected array at {path}",
                schema_name=schema_name,
                path=path,
                details={"expected_type": "array", "actual_type": type(value).__name__},
            )
        item_schema = dict(schema.get("items", {}) or {})
        for index, item in enumerate(value):
            _validate_json_schema(schema_name, item_schema, item, path=f"{path}[{index}]")
        return
    if schema_type == "string":
        if not isinstance(value, str):
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} expected string at {path}",
                schema_name=schema_name,
                path=path,
                details={"expected_type": "string", "actual_type": type(value).__name__},
            )
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} expected boolean at {path}",
                schema_name=schema_name,
                path=path,
                details={"expected_type": "boolean", "actual_type": type(value).__name__},
            )
    elif schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} expected number at {path}",
                schema_name=schema_name,
                path=path,
                details={"expected_type": "number", "actual_type": type(value).__name__},
            )
    elif schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} expected integer at {path}",
                schema_name=schema_name,
                path=path,
                details={"expected_type": "integer", "actual_type": type(value).__name__},
            )
    if "enum" in schema:
        allowed = list(schema.get("enum", []))
        if value not in allowed:
            _raise_schema_error(
                "malformed_output",
                f"{schema_name} value at {path} is outside enum",
                schema_name=schema_name,
                path=path,
                details={"allowed": allowed, "actual": value},
            )


def invoke_structured_response(
    openai_config: Mapping[str, Any],
    *,
    system_prompt: str,
    user_payload: Mapping[str, Any] | str,
    schema_name: str,
    schema: Mapping[str, Any],
) -> StructuredResponseResult:
    status = _bootstrap_openai_operation(openai_config)
    api_key = os.environ[str(status["api_key_env"])].strip()
    user_text = user_payload if isinstance(user_payload, str) else json.dumps(user_payload, indent=2, sort_keys=True)
    payload: dict[str, Any] = {
        "model": status["model"],
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": dict(schema),
                "strict": True,
            }
        },
    }
    reasoning_effort = str(openai_config.get("reasoning_effort", "") or "").strip()
    reasoning_summary = str(openai_config.get("reasoning_summary", "") or "").strip()
    if reasoning_effort or reasoning_summary:
        reasoning: dict[str, Any] = {}
        if reasoning_effort:
            reasoning["effort"] = reasoning_effort
        if reasoning_summary:
            reasoning["summary"] = reasoning_summary
        payload["reasoning"] = reasoning
    if "max_output_tokens" in openai_config:
        payload["max_output_tokens"] = int(openai_config["max_output_tokens"])

    http_request = request.Request(
        str(status["responses_api"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=int(status["timeout_seconds"])) as response:
            raw_response_text = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIResponsesError(
            "api_failure",
            f"Responses API HTTP {exc.code}",
            details={"http_status": exc.code, "body_excerpt": body[:500]},
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OpenAIResponsesError("timeout", "Responses API request timed out") from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", "")
        if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
            raise OpenAIResponsesError("timeout", "Responses API request timed out") from exc
        raise OpenAIResponsesError(
            "api_failure",
            f"Responses API request failed: {reason}",
            details={"reason": str(reason)},
        ) from exc

    try:
        response_payload = json.loads(raw_response_text)
    except json.JSONDecodeError as exc:
        raise OpenAIResponsesError(
            "malformed_output",
            "Responses API returned a malformed JSON envelope",
            details={"body_excerpt": raw_response_text[:500]},
        ) from exc
    if not isinstance(response_payload, Mapping):
        raise OpenAIResponsesError("malformed_output", "Responses API envelope must be a JSON object")

    refusal_text = ""
    parsed_payload: dict[str, Any] | None = None
    output_text_parts: list[str] = []
    for item in list(response_payload.get("output", [])):
        if not isinstance(item, Mapping) or str(item.get("type", "")) != "message":
            continue
        for content in list(item.get("content", [])):
            if not isinstance(content, Mapping):
                continue
            content_type = str(content.get("type", ""))
            if content_type == "refusal":
                refusal_text = str(content.get("refusal", "")).strip()
            elif content_type == "output_text":
                if isinstance(content.get("parsed"), Mapping):
                    parsed_payload = dict(content["parsed"])
                text = str(content.get("text", ""))
                if text:
                    output_text_parts.append(text)
    if refusal_text:
        raise OpenAIResponsesError("api_failure", f"Responses API refusal: {refusal_text}")

    output_text = "".join(output_text_parts).strip()
    if parsed_payload is None:
        if not output_text:
            raise OpenAIResponsesError("malformed_output", "Responses API returned no structured output text")
        try:
            parsed_candidate = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIResponsesError(
                "non_json_output",
                "Responses API returned non-JSON structured output text",
                details={"output_excerpt": output_text[:500]},
            ) from exc
        if not isinstance(parsed_candidate, Mapping):
            raise OpenAIResponsesError("malformed_output", "Responses API structured output must be a JSON object")
        parsed_payload = dict(parsed_candidate)

    if bool(status.get("strict_schema_validation", True)):
        _validate_json_schema(schema_name, schema, parsed_payload)

    response_status = str(response_payload.get("status", "completed") or "completed")
    if response_status not in {"completed", "incomplete"}:
        raise OpenAIResponsesError(
            "api_failure",
            f"Responses API response status was {response_status}",
            details={"response_status": response_status},
        )

    return StructuredResponseResult(
        response_id=str(response_payload.get("id", "")),
        model=str(response_payload.get("model", status["model"])),
        status=response_status,
        parsed=parsed_payload,
        output_text=output_text,
        usage=dict(response_payload.get("usage", {}) or {}),
    )
