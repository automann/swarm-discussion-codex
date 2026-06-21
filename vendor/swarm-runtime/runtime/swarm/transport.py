"""Runtime-owned host transport artifact helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from swarm._shared import fsync_dir as _fsync_dir
from swarm.adapter import ALLOWED_HOSTS, validate_host_transport_metadata
from swarm.collect import collect_merge

SCHEMA_VERSION = 1
DEFAULT_COMMAND_PREFIX = "swarm-rt"
PHASE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
_INVOCATION_FORMS = {"explicit_spawn", "at_mention"}
_DESCRIPTOR_OPTIONAL_STR = ("projectedPath", "agentType", "promptRef")


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _phase_dir(discussion_dir: Path, round_id: int, phase: str) -> Path:
    return discussion_dir / "transport" / f"r{round_id:03d}" / phase


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp_path.open("w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    _fsync_dir(path.parent)


def _write_json_atomic(path: Path, payload: Any) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def transport_paths(discussion_dir: Path, round_id: int, phase: str) -> dict[str, Path]:
    phase_dir = _phase_dir(discussion_dir, round_id, phase)
    return {
        "phaseDir": phase_dir,
        "spawnOrderPath": phase_dir / "spawn-order.json",
        "waitBatchesPath": phase_dir / "wait-batches.jsonl",
        "collectResultPath": phase_dir / "collect-result.json",
        "hostStepPath": phase_dir / "host-step.json",
    }


def _agent_id(spec: dict[str, Any]) -> str | None:
    value = spec.get("agentId") or spec.get("agent_id")
    return str(value) if value is not None else None


def _validate_agent_descriptor(descriptor: Any, path: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Validate an optional host-agnostic projected custom-agent descriptor (plan 007)."""
    if not isinstance(descriptor, dict):
        return None, [_issue("invalid_agent_descriptor", path, "agentDescriptor must be an object")]

    errors: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}

    projected_name = descriptor.get("projectedName")
    if not isinstance(projected_name, str) or not projected_name.strip():
        errors.append(
            _issue("invalid_agent_descriptor", f"{path}.projectedName", "projectedName is required and must be a non-empty string")
        )
    else:
        normalized["projectedName"] = projected_name

    sha = descriptor.get("projectedSha256")
    if sha is not None:
        if not isinstance(sha, str) or not _SHA256.match(sha):
            errors.append(
                _issue("invalid_agent_descriptor", f"{path}.projectedSha256", "projectedSha256 must be 64 lowercase hex characters", sha)
            )
        else:
            normalized["projectedSha256"] = sha

    invocation = descriptor.get("invocationForm")
    if invocation is not None:
        if invocation not in _INVOCATION_FORMS:
            errors.append(
                _issue("invalid_agent_descriptor", f"{path}.invocationForm", "invocationForm must be explicit_spawn or at_mention", invocation)
            )
        else:
            normalized["invocationForm"] = invocation

    for field in _DESCRIPTOR_OPTIONAL_STR:
        value = descriptor.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            errors.append(_issue("invalid_agent_descriptor", f"{path}.{field}", f"{field} must be a non-empty string"))
        else:
            normalized[field] = value

    return (normalized if not errors else None), errors


def _validate_spawn_order(spawn_order: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(spawn_order, list) or not spawn_order:
        return [], [_issue("invalid_spawn_order", "spawnOrder", "spawn order must be a non-empty list")]

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(spawn_order):
        path = f"spawnOrder[{index}]"
        if not isinstance(item, dict):
            errors.append(_issue("invalid_spawn_order_item", path, "spawn-order item must be an object"))
            continue
        agent_id = _agent_id(item)
        persona = item.get("persona") or item.get("name")
        if not agent_id:
            errors.append(_issue("missing_agent_id", f"{path}.agentId", "agentId is required"))
            continue
        if agent_id in seen:
            errors.append(_issue("duplicate_agent_id", f"{path}.agentId", "agentId must be unique", agent_id))
            continue
        if not isinstance(persona, str) or not persona.strip():
            errors.append(_issue("missing_persona", f"{path}.persona", "persona is required"))
            continue
        seen.add(agent_id)
        normalized_item = {"agentId": agent_id, "persona": persona}
        if item.get("token"):
            normalized_item["token"] = str(item["token"])
        if "agentDescriptor" in item:
            descriptor, descriptor_errors = _validate_agent_descriptor(
                item["agentDescriptor"], f"{path}.agentDescriptor"
            )
            if descriptor_errors:
                errors.extend(descriptor_errors)
                continue
            normalized_item["agentDescriptor"] = descriptor
        normalized.append(normalized_item)
    return normalized, errors


def _validate_step_inputs(
    host: str | None,
    discussion_id: str | None,
    round_id: int,
    phase: str | None,
    brief_path: str | None = "context/summary.md",
    command_prefix: str | None = DEFAULT_COMMAND_PREFIX,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if host is not None and host not in ALLOWED_HOSTS:
        errors.append(_issue("invalid_host", "host", "host must be codex or claude", host))
    if discussion_id is not None and (not isinstance(discussion_id, str) or not discussion_id.strip()):
        errors.append(_issue("missing_discussion_id", "discussionId", "discussionId is required"))
    if round_id < 1:
        errors.append(_issue("invalid_round", "round", "round must be >= 1", round_id))
    if phase is not None:
        if not isinstance(phase, str) or not phase.strip():
            errors.append(_issue("missing_phase", "phase", "phase is required"))
        elif not PHASE_NAME.match(phase):
            errors.append(
                _issue(
                    "invalid_phase",
                    "phase",
                    "phase must contain only letters, numbers, underscore, or hyphen",
                    phase,
                )
            )
    if brief_path is not None and (not isinstance(brief_path, str) or not brief_path.strip()):
        errors.append(_issue("missing_brief_path", "briefPath", "briefPath is required"))
    if command_prefix is not None and (not isinstance(command_prefix, str) or not command_prefix.strip()):
        errors.append(_issue("missing_command_prefix", "commandPrefix", "commandPrefix is required"))
    return errors


def _runtime_commands(command_prefix: str, round_id: int, phase: str) -> dict[str, str]:
    transport_prefix = f"transport/r{round_id:03d}/{phase}"
    return {
        "contextBuild": f"{command_prefix} context-build --brief brief.json --out context/summary.md",
        "promptBuild": (
            f"{command_prefix} prompt-build --request prompts/r{round_id:03d}/{phase}/<agent-id>/request.json "
            f"--out-dir prompts/r{round_id:03d}/{phase}/<agent-id>"
        ),
        "collectMerge": (
            f"{command_prefix} collect-merge --spawn-order {transport_prefix}/spawn-order.json "
            f"--wait-result {transport_prefix}/wait-batches.jsonl"
        ),
        "appendMessage": f"{command_prefix} append-message --dir . --round {round_id} --phase {phase} --message <message.json>",
        "checkpoint": f"{command_prefix} checkpoint --dir . --round {round_id} --phase {phase} --state rounds/{round_id:03d}.json.partial",
        "finalizeRound": f"{command_prefix} finalize-round --dir . --round {round_id} --state rounds/{round_id:03d}.json",
        "trace": f"{command_prefix} trace --dir .",
        "evidence": f"{command_prefix} evidence --dir . --output artifacts/evidence.json",
    }


def write_transport_step(
    discussion_dir: Path,
    host: str,
    discussion_id: str,
    round_id: int,
    phase: str,
    spawn_order: Any,
    brief_path: str = "context/summary.md",
    command_prefix: str = DEFAULT_COMMAND_PREFIX,
    agent_source_dir: str | None = None,
) -> dict[str, Any]:
    normalized_spawn_order, errors = _validate_spawn_order(spawn_order)
    errors.extend(_validate_step_inputs(host, discussion_id, round_id, phase, brief_path, command_prefix))
    if errors:
        return {"ok": False, "errors": errors}

    paths = transport_paths(discussion_dir, round_id, phase)
    rel_spawn = _relative(paths["spawnOrderPath"], discussion_dir)
    rel_wait = _relative(paths["waitBatchesPath"], discussion_dir)
    rel_collect = _relative(paths["collectResultPath"], discussion_dir)
    rel_host = _relative(paths["hostStepPath"], discussion_dir)
    transport_block: dict[str, Any] = {
        "spawnPrimitive": "multi_agent_v1.spawn_agent" if host == "codex" else "Agent",
        "waitPrimitive": "multi_agent_v1.wait_agent" if host == "codex" else "Agent result collection",
        "resultKey": "agent_id" if host == "codex" else "name",
        "partialBatches": True,
        "rawHostLogs": {"required": False},
    }
    descriptor_entries = [item for item in normalized_spawn_order if item.get("agentDescriptor")]
    if descriptor_entries:
        source_dir = agent_source_dir
        if not source_dir:
            first_path = descriptor_entries[0]["agentDescriptor"].get("projectedPath")
            source_dir = str(Path(first_path).parent) if first_path else ""
        transport_block["customAgentProjection"] = {
            "projected": True,
            "agentSourceDir": source_dir,
            "count": len(descriptor_entries),
        }
    host_step = {
        "schemaVersion": SCHEMA_VERSION,
        "host": host,
        "discussionId": discussion_id,
        "round": round_id,
        "phase": phase,
        "parentContext": {
            "briefPath": brief_path,
            "phase": phase,
            "agentIds": [item["agentId"] for item in normalized_spawn_order],
            "nextHelperCommand": (
                f"{command_prefix} transport-collect --dir . --round {round_id} --phase {phase}"
            ),
        },
        "runtimeCommands": _runtime_commands(command_prefix, round_id, phase),
        "transport": transport_block,
        "artifacts": {
            "spawnOrderPath": rel_spawn,
            "waitBatchesPath": rel_wait,
            "collectResultPath": rel_collect,
            "hostStepPath": rel_host,
        },
    }

    validation = validate_host_transport_metadata(host_step)
    if not validation["ok"]:
        return {"ok": False, "errors": validation["errors"], "paths": {key: str(value) for key, value in paths.items()}}

    if paths["waitBatchesPath"].exists() and paths["waitBatchesPath"].read_text().strip():
        existing_spawn_order, existing_issue = (
            _load_json(paths["spawnOrderPath"]) if paths["spawnOrderPath"].exists() else (None, None)
        )
        if existing_issue is not None or existing_spawn_order != normalized_spawn_order:
            return {
                "ok": False,
                "errors": [
                    _issue(
                        "stale_wait_batches",
                        str(paths["waitBatchesPath"]),
                        "wait batches exist from a previous spawn order; collect or clear them before re-initializing",
                    )
                ],
                "paths": {key: str(value) for key, value in paths.items()},
            }

    _write_json_atomic(paths["spawnOrderPath"], normalized_spawn_order)
    _write_json_atomic(paths["hostStepPath"], host_step)
    if not paths["waitBatchesPath"].exists():
        _write_text_atomic(paths["waitBatchesPath"], "")
    return {
        "ok": True,
        "errors": [],
        "paths": {key: str(value) for key, value in paths.items()},
        "hostStep": host_step,
        "validation": validation,
    }


def append_wait_batch(discussion_dir: Path, round_id: int, phase: str, wait_result: Any) -> dict[str, Any]:
    errors = _validate_step_inputs(None, None, round_id, phase, None, None)
    if not isinstance(wait_result, dict):
        errors.append(_issue("invalid_wait_result", "waitResult", "wait result must be an object"))
    paths = transport_paths(discussion_dir, round_id, phase)
    if not paths["hostStepPath"].exists():
        errors.append(_issue("missing_host_step", str(paths["hostStepPath"]), "transport-init must run before appending batches"))
    if not paths["spawnOrderPath"].exists():
        errors.append(_issue("missing_spawn_order", str(paths["spawnOrderPath"]), "transport-init must run before appending batches"))
    if errors:
        return {"ok": False, "errors": errors, "paths": {key: str(value) for key, value in paths.items()}}

    paths["phaseDir"].mkdir(parents=True, exist_ok=True)
    with paths["waitBatchesPath"].open("a") as handle:
        handle.write(json.dumps(wait_result, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "ok": True,
        "errors": [],
        "path": str(paths["waitBatchesPath"]),
    }


def _load_json(path: Path) -> tuple[Any, dict[str, Any] | None]:
    try:
        return json.loads(path.read_text()), None
    except OSError as exc:
        return None, _issue("unreadable_file", str(path), f"cannot read file: {exc}")
    except json.JSONDecodeError as exc:
        return None, _issue("invalid_json", str(path), f"invalid JSON: {exc}")


def _load_wait_batches(path: Path) -> tuple[list[Any], list[dict[str, Any]]]:
    if not path.exists():
        return [], []
    batches: list[Any] = []
    issues: list[dict[str, Any]] = []
    try:
        text = path.read_text()
    except OSError as exc:
        return [], [_issue("unreadable_file", str(path), f"cannot read file: {exc}")]
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            batches.append(json.loads(line))
        except json.JSONDecodeError as exc:
            issues.append(_issue("invalid_jsonl", f"{path}:{line_number}", f"invalid JSONL: {exc}"))
    return batches, issues


def collect_transport_step(discussion_dir: Path, round_id: int, phase: str) -> dict[str, Any]:
    paths = transport_paths(discussion_dir, round_id, phase)
    errors = _validate_step_inputs(None, None, round_id, phase, None, None)
    spawn_order: Any = None
    if paths["spawnOrderPath"].exists():
        spawn_order, spawn_issue = _load_json(paths["spawnOrderPath"])
        if spawn_issue is not None:
            errors.append(spawn_issue)
        elif not isinstance(spawn_order, list):
            errors.append(_issue("invalid_spawn_order", str(paths["spawnOrderPath"]), "spawn order must be a list"))
            spawn_order = None
    else:
        errors.append(_issue("missing_spawn_order", str(paths["spawnOrderPath"]), "spawn-order.json is missing"))
    if not paths["waitBatchesPath"].exists():
        errors.append(_issue("missing_wait_batches", str(paths["waitBatchesPath"]), "wait-batches.jsonl is missing"))
    host_step_validation = None
    if paths["hostStepPath"].exists():
        host_step_payload, host_step_issue = _load_json(paths["hostStepPath"])
        if host_step_issue is not None:
            errors.append(host_step_issue)
        else:
            host_step_validation = validate_host_transport_metadata(host_step_payload)
            if not host_step_validation["ok"]:
                errors.extend(host_step_validation["errors"])
    else:
        errors.append(_issue("missing_host_step", str(paths["hostStepPath"]), "host-step.json is missing"))
    wait_batches, wait_issues = _load_wait_batches(paths["waitBatchesPath"])
    errors.extend(wait_issues)
    if errors:
        blocking = {
            "missing_spawn_order",
            "invalid_spawn_order",
            "missing_wait_batches",
            "invalid_phase",
            "invalid_round",
            "invalid_json",
            "unreadable_file",
        }
        if spawn_order is None or any(error["code"] in blocking for error in errors):
            return {
                "ok": False,
                "errors": errors,
                "paths": {key: str(value) for key, value in paths.items()},
                "hostStepValidation": host_step_validation,
            }

    result = collect_merge(spawn_order, wait_batches)
    _write_json_atomic(paths["collectResultPath"], result)
    all_errors = [*errors, *result["errors"]]
    return {
        "ok": result["ok"] and not errors,
        "errors": all_errors,
        "paths": {key: str(value) for key, value in paths.items()},
        "result": result,
        "hostStepValidation": host_step_validation,
    }
