"""Adapter-facing smoke checks for host-produced discussion artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm.adapter import validate_host_transport_metadata
from swarm.audit import build_evidence, build_trace
from swarm.collect import collect_merge
from swarm.loop import validate_minimal_loop


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, _issue("missing_file", str(path), f"missing file: {path}")
    except json.JSONDecodeError as exc:
        return None, _issue("invalid_json", str(path), f"invalid JSON: {exc}")


def _load_wait_batches(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = ""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return [], [_issue("missing_file", str(path), f"missing file: {path}")]

    if path.suffix != ".jsonl":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(payload, dict):
                return [payload], []
            return [], [_issue("invalid_wait_result", str(path), "wait result must be a JSON object")]

    batches: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(_issue("invalid_jsonl", f"{path}:{line_number}", f"invalid JSONL: {exc}"))
            continue
        if isinstance(payload, dict):
            batches.append(payload)
        else:
            errors.append(_issue("invalid_wait_result", f"{path}:{line_number}", "wait result must be a JSON object"))
    return batches, errors


def _resolve_artifact_path(discussion_dir: Path, artifact_path: Any) -> Path | None:
    if not isinstance(artifact_path, str) or not artifact_path.strip():
        return None
    if "\\" in artifact_path:
        return None
    parts = artifact_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return discussion_dir / artifact_path


def _result_core(item: dict[str, Any]) -> dict[str, Any]:
    core = {
        "persona": item.get("persona"),
        "agentId": item.get("agentId"),
        "result": item.get("result"),
    }
    # Provenance must survive the replay comparison: a stored collect-result that
    # drops or mutates agentDescriptor must NOT match the rebuilt output, or the
    # certification boundary would accept bogus projection provenance (plan 007).
    if "agentDescriptor" in item:
        core["agentDescriptor"] = item.get("agentDescriptor")
    return core


def _collect_core(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": payload.get("ok"),
        "complete": payload.get("complete"),
        "timedOut": payload.get("timedOut"),
        "requiredAgentIds": payload.get("requiredAgentIds") or [],
        "receivedAgentIds": payload.get("receivedAgentIds") or [],
        "missingAgentIds": payload.get("missingAgentIds") or [],
        "missingPersonas": payload.get("missingPersonas") or [],
        "results": [
            _result_core(item)
            for item in payload.get("results", []) or []
            if isinstance(item, dict)
        ],
        "errors": payload.get("errors") or [],
    }


def _transport_replay(
    discussion_dir: Path, host_step_path: Path, host_step: dict[str, Any]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    artifacts = host_step.get("artifacts") if isinstance(host_step.get("artifacts"), dict) else {}
    spawn_order_path = _resolve_artifact_path(discussion_dir, artifacts.get("spawnOrderPath"))
    wait_batches_path = _resolve_artifact_path(discussion_dir, artifacts.get("waitBatchesPath"))
    collect_result_path = _resolve_artifact_path(discussion_dir, artifacts.get("collectResultPath"))

    missing_paths = {
        "spawnOrderPath": spawn_order_path,
        "waitBatchesPath": wait_batches_path,
        "collectResultPath": collect_result_path,
    }
    for field, path in missing_paths.items():
        if path is None:
            errors.append(
                _issue(
                    "missing_artifact_path",
                    f"{host_step_path}:artifacts.{field}",
                    "artifact path must be a relative path inside the discussion directory",
                )
            )

    spawn_order: Any = []
    if spawn_order_path is not None:
        spawn_order, load_error = _load_json(spawn_order_path)
        if load_error:
            errors.append(load_error)
        elif not isinstance(spawn_order, list):
            errors.append(_issue("invalid_spawn_order", str(spawn_order_path), "spawn order must be a list"))
            spawn_order = []

    wait_batches: list[dict[str, Any]] = []
    if wait_batches_path is not None:
        wait_batches, wait_errors = _load_wait_batches(wait_batches_path)
        errors.extend(wait_errors)

    stored_collect: Any = {}
    stored_loaded = False
    if collect_result_path is not None:
        stored_collect, load_error = _load_json(collect_result_path)
        if load_error:
            errors.append(load_error)
        elif not isinstance(stored_collect, dict):
            errors.append(_issue("invalid_collect_result", str(collect_result_path), "collect result must be an object"))
            stored_collect = {}
        else:
            stored_loaded = True

    replay = collect_merge(spawn_order if isinstance(spawn_order, list) else [], wait_batches)
    if stored_loaded and _collect_core(stored_collect) != _collect_core(replay):
        errors.append(
            _issue(
                "collect_replay_mismatch",
                str(collect_result_path),
                "stored collect-result does not match replayed collect-merge output",
                {"stored": _collect_core(stored_collect), "replay": _collect_core(replay)},
            )
        )

    if not replay.get("ok"):
        errors.append(
            _issue(
                "collect_replay_failed",
                str(wait_batches_path) if wait_batches_path else str(host_step_path),
                "replayed collect-merge is not ok",
                replay,
            )
        )

    return {
        "ok": not errors,
        "errors": errors,
        "hostStepPath": str(host_step_path),
        "paths": {
            "spawnOrderPath": str(spawn_order_path) if spawn_order_path else None,
            "waitBatchesPath": str(wait_batches_path) if wait_batches_path else None,
            "collectResultPath": str(collect_result_path) if collect_result_path else None,
        },
        "batchCount": len(wait_batches),
        "replay": replay,
        "stored": _collect_core(stored_collect) if isinstance(stored_collect, dict) else {},
    }


def _host_step_paths(discussion_dir: Path, host_step_path: Path | None) -> list[Path]:
    if host_step_path:
        return [host_step_path if host_step_path.is_absolute() else discussion_dir / host_step_path]
    return sorted((discussion_dir / "transport").glob("**/host-step.json"))


def adapter_smoke(discussion_dir: Path, host_step_path: Path | None = None) -> dict[str, Any]:
    """Run adapter-facing smoke checks without spawning agents or mutating state."""

    errors: list[dict[str, Any]] = []
    if not discussion_dir.exists():
        return {
            "ok": False,
            "errors": [_issue("missing_directory", str(discussion_dir), "discussion directory does not exist")],
        }
    if not discussion_dir.is_dir():
        return {
            "ok": False,
            "errors": [_issue("invalid_directory", str(discussion_dir), "discussion path is not a directory")],
        }

    host_step_reports: list[dict[str, Any]] = []
    replays: list[dict[str, Any]] = []
    paths = _host_step_paths(discussion_dir, host_step_path)
    if not paths:
        errors.append(_issue("missing_host_step", str(discussion_dir / "transport"), "no host-step.json found"))

    for path in paths:
        payload, load_error = _load_json(path)
        if load_error:
            errors.append(load_error)
            continue
        if not isinstance(payload, dict):
            errors.append(_issue("invalid_host_step", str(path), "host-step must be a JSON object"))
            continue

        host_result = validate_host_transport_metadata(payload)
        host_step_reports.append({"path": str(path), **host_result})
        if not host_result["ok"]:
            errors.extend(host_result["errors"])
            continue

        replay = _transport_replay(discussion_dir, path, payload)
        replays.append(replay)
        if not replay["ok"]:
            errors.extend(replay["errors"])

    trace = build_trace(discussion_dir)
    evidence = build_evidence(discussion_dir)
    loop = validate_minimal_loop(discussion_dir)
    if not trace.get("ok"):
        errors.extend(trace.get("errors", []))
    if not evidence.get("ok"):
        errors.extend(evidence.get("errors", []))
    if not loop.get("ok"):
        errors.extend(loop.get("errors", []))

    capabilities = trace.get("capabilities", {})
    summary = {
        "discussionId": trace.get("discussion", {}).get("id"),
        "health": trace.get("health"),
        "hostStepCount": len(host_step_reports),
        "transportReplayCount": len(replays),
        "transportReplayOk": bool(replays) and all(replay.get("ok") for replay in replays),
        "capabilityProfile": capabilities.get("profile", {}).get("id"),
        "citableToolEvidence": capabilities.get("toolEvidence", {}).get("citable", False),
        "outcome": evidence.get("outcome", {}).get("result"),
        "loopOk": loop.get("ok", False),
    }
    return {
        "ok": not errors,
        "errors": errors,
        "summary": summary,
        "hostSteps": host_step_reports,
        "transportReplays": replays,
        "trace": {
            "health": trace.get("health"),
            "nextAction": trace.get("nextAction"),
        },
        "evidence": {
            "outcome": evidence.get("outcome"),
            "metrics": evidence.get("metrics"),
        },
        "loop": {
            "ok": loop.get("ok"),
            "summary": loop.get("summary", {}),
        },
    }
