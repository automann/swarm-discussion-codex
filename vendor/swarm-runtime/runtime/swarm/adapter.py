"""Thin host-adapter contract validation.

This module does not spawn agents. It validates the small metadata packet a
host adapter writes while runtime helpers own prompt, transport merge, WAL, and
audit semantics.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1
ALLOWED_HOSTS = {"codex", "claude"}
ALLOWED_PARENT_CONTEXT_KEYS = {"briefPath", "phase", "agentIds", "nextHelperCommand"}
FORBIDDEN_PARENT_CONTEXT_KEYS = {
    "argumentGraph",
    "discussionHistory",
    "fullDiscussionHistory",
    "fullPrompt",
    "manualDemuxMap",
    "messages",
    "promptText",
    "rawHostLog",
    "rawHostLogs",
    "roundState",
    "waitResults",
}
REQUIRED_ROOT_FIELDS = {
    "schemaVersion",
    "host",
    "discussionId",
    "round",
    "phase",
    "parentContext",
    "runtimeCommands",
    "transport",
    "artifacts",
}
REQUIRED_RUNTIME_COMMANDS = {
    "contextBuild",
    "promptBuild",
    "collectMerge",
    "appendMessage",
    "checkpoint",
    "finalizeRound",
    "trace",
    "evidence",
}
REQUIRED_TRANSPORT_FIELDS = {"spawnPrimitive", "waitPrimitive", "resultKey"}
REQUIRED_ARTIFACT_FIELDS = {"spawnOrderPath", "waitBatchesPath", "collectResultPath"}


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _require_mapping(value: Any, path: str, errors: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(_issue("invalid_type", path, "must be a JSON object"))
        return {}
    return value


def _valid_relative_path(value: str) -> bool:
    if "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _require_relative_path(
    mapping: dict[str, Any],
    field: str,
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        return
    if not _valid_relative_path(value):
        errors.append(
            _issue(
                "invalid_artifact_path",
                f"{path}.{field}",
                "artifact path must stay relative inside the discussion directory",
                value,
            )
        )


def _require_non_empty_string(
    mapping: dict[str, Any],
    field: str,
    path: str,
    errors: list[dict[str, Any]],
) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(_issue("missing_string", f"{path}.{field}", "must be a non-empty string"))
        return ""
    return value


def _require_positive_int(
    mapping: dict[str, Any],
    field: str,
    path: str,
    errors: list[dict[str, Any]],
) -> int | None:
    value = mapping.get(field)
    if not isinstance(value, int) or value < 1:
        errors.append(_issue("invalid_integer", f"{path}.{field}", "must be a positive integer"))
        return None
    return value


def parent_context_surface(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only the allowed parent-context surface for audit display."""

    parent_context = payload.get("parentContext")
    if not isinstance(parent_context, dict):
        return {}
    return {key: parent_context[key] for key in sorted(ALLOWED_PARENT_CONTEXT_KEYS) if key in parent_context}


def validate_host_transport_metadata(payload: Any) -> dict[str, Any]:
    """Validate one host-step metadata packet.

    The key invariant is deliberately narrow: parent context may contain only
    the brief path, current phase, agent ids, and the next helper command.
    """

    errors: list[dict[str, Any]] = []
    packet = _require_mapping(payload, "hostStep", errors)
    if not packet:
        return {"ok": False, "errors": errors}

    missing_root = sorted(REQUIRED_ROOT_FIELDS - set(packet))
    for field in missing_root:
        errors.append(_issue("missing_field", f"hostStep.{field}", "required field is missing"))

    schema_version = packet.get("schemaVersion")
    if schema_version != SCHEMA_VERSION:
        errors.append(
            _issue(
                "unsupported_schema_version",
                "hostStep.schemaVersion",
                f"must be {SCHEMA_VERSION}",
                schema_version,
            )
        )

    host = packet.get("host")
    if host not in ALLOWED_HOSTS:
        errors.append(_issue("invalid_host", "hostStep.host", "must be 'codex' or 'claude'", host))

    round_id = _require_positive_int(packet, "round", "hostStep", errors)
    phase = _require_non_empty_string(packet, "phase", "hostStep", errors)
    discussion_id = _require_non_empty_string(packet, "discussionId", "hostStep", errors)

    parent_context = _require_mapping(packet.get("parentContext"), "hostStep.parentContext", errors)
    if isinstance(packet.get("parentContext"), dict):
        extra_keys = sorted(set(parent_context) - ALLOWED_PARENT_CONTEXT_KEYS)
        for key in extra_keys:
            code = "forbidden_parent_context" if key in FORBIDDEN_PARENT_CONTEXT_KEYS else "unknown_parent_context"
            errors.append(
                _issue(
                    code,
                    f"hostStep.parentContext.{key}",
                    "parent context is limited to briefPath, phase, agentIds, and nextHelperCommand",
                )
            )
        for field in sorted(ALLOWED_PARENT_CONTEXT_KEYS - set(parent_context)):
            errors.append(_issue("missing_field", f"hostStep.parentContext.{field}", "required field is missing"))
        _require_non_empty_string(parent_context, "briefPath", "hostStep.parentContext", errors)
        parent_phase = _require_non_empty_string(parent_context, "phase", "hostStep.parentContext", errors)
        _require_non_empty_string(
            parent_context,
            "nextHelperCommand",
            "hostStep.parentContext",
            errors,
        )
        agent_ids = parent_context.get("agentIds")
        if not isinstance(agent_ids, list) or not agent_ids or not all(
            isinstance(agent_id, str) and agent_id.strip() for agent_id in agent_ids
        ):
            errors.append(
                _issue(
                    "invalid_agent_ids",
                    "hostStep.parentContext.agentIds",
                    "must be a non-empty list of strings",
                )
            )
        if parent_phase and phase and parent_phase != phase:
            errors.append(
                _issue(
                    "phase_mismatch",
                    "hostStep.parentContext.phase",
                    "parent context phase must match host step phase",
                    {"parentContext": parent_phase, "hostStep": phase},
                )
            )

    runtime_commands = _require_mapping(packet.get("runtimeCommands"), "hostStep.runtimeCommands", errors)
    if isinstance(packet.get("runtimeCommands"), dict):
        for field in sorted(REQUIRED_RUNTIME_COMMANDS - set(runtime_commands)):
            errors.append(_issue("missing_field", f"hostStep.runtimeCommands.{field}", "required command is missing"))
        for field in sorted(REQUIRED_RUNTIME_COMMANDS & set(runtime_commands)):
            _require_non_empty_string(runtime_commands, field, "hostStep.runtimeCommands", errors)

    transport = _require_mapping(packet.get("transport"), "hostStep.transport", errors)
    if isinstance(packet.get("transport"), dict):
        for field in sorted(REQUIRED_TRANSPORT_FIELDS - set(transport)):
            errors.append(_issue("missing_field", f"hostStep.transport.{field}", "required field is missing"))
        for field in sorted(REQUIRED_TRANSPORT_FIELDS & set(transport)):
            _require_non_empty_string(transport, field, "hostStep.transport", errors)
        result_key = transport.get("resultKey")
        if result_key and result_key not in {"agent_id", "name"}:
            errors.append(
                _issue(
                    "invalid_result_key",
                    "hostStep.transport.resultKey",
                    "must be 'agent_id' or 'name'",
                    result_key,
                )
            )
        raw_host_logs = transport.get("rawHostLogs")
        if isinstance(raw_host_logs, dict) and raw_host_logs.get("required") is True:
            errors.append(
                _issue(
                    "raw_host_logs_required",
                    "hostStep.transport.rawHostLogs.required",
                    "raw host logs must remain optional secondary evidence",
                )
            )
        projection = transport.get("customAgentProjection")
        if projection is not None:
            base = "hostStep.transport.customAgentProjection"
            if not isinstance(projection, dict):
                errors.append(_issue("invalid_custom_agent_projection", base, "customAgentProjection must be an object"))
            else:
                if not isinstance(projection.get("projected"), bool):
                    errors.append(_issue("invalid_custom_agent_projection", f"{base}.projected", "projected is required and must be a boolean"))
                source_dir = projection.get("agentSourceDir")
                if source_dir is not None and (not isinstance(source_dir, str) or not source_dir.strip()):
                    errors.append(_issue("invalid_custom_agent_projection", f"{base}.agentSourceDir", "agentSourceDir must be a non-empty string"))
                count = projection.get("count")
                if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                    errors.append(_issue("invalid_custom_agent_projection", f"{base}.count", "count must be a non-negative integer", count))
                extra = sorted(set(projection) - {"projected", "agentSourceDir", "count"})
                if extra:
                    errors.append(_issue("invalid_custom_agent_projection", base, "unexpected keys in customAgentProjection", extra))

    artifacts = _require_mapping(packet.get("artifacts"), "hostStep.artifacts", errors)
    if isinstance(packet.get("artifacts"), dict):
        for field in sorted(REQUIRED_ARTIFACT_FIELDS - set(artifacts)):
            errors.append(_issue("missing_field", f"hostStep.artifacts.{field}", "required artifact path is missing"))
        for field in sorted(REQUIRED_ARTIFACT_FIELDS & set(artifacts)):
            _require_non_empty_string(artifacts, field, "hostStep.artifacts", errors)
        for field in sorted(artifacts):
            _require_relative_path(artifacts, field, "hostStep.artifacts", errors)

    summary = {
        "schemaVersion": schema_version,
        "host": host,
        "discussionId": discussion_id,
        "round": round_id,
        "phase": phase,
        "parentContextSurface": parent_context_surface(packet),
        "runtimeCommandCount": len(runtime_commands),
        "artifactCount": len(artifacts),
    }
    return {"ok": not errors, "errors": errors, "summary": summary}
