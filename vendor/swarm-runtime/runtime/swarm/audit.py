"""Trace and evidence builders for discussion artifact directories."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from swarm.capabilities import (
    capability_doctor_report,
    default_profile_path,
    load_jsonl as load_tool_evidence_jsonl,
)
from swarm.validation import validate_discussion_dir, validate_round_file
from swarm.wal import resume_plan

SCHEMA_VERSION = 1
TRACE_KIND = "swarm.discussion_trace"
EVIDENCE_KIND = "swarm.discussion_evidence"


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, _issue("missing_file", str(path), f"missing file: {path}")
    except json.JSONDecodeError as exc:
        return None, _issue("invalid_json", str(path), f"invalid JSON: {exc}")


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return events, errors
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(_issue("invalid_jsonl", f"{path}:{line_number}", f"invalid JSONL: {exc}"))
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            errors.append(_issue("invalid_event", f"{path}:{line_number}", "event must be a JSON object"))
    return events, errors


def _manifest_summary(discussion_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest, error = _load_json(discussion_dir / "manifest.json")
    if error:
        return {}, [error]
    if not isinstance(manifest, dict):
        return {}, [_issue("invalid_manifest", "manifest.json", "manifest must be a JSON object")]
    return manifest, []


def _round_value(payload: dict[str, Any], path: Path) -> Any:
    for key in ("roundId", "round"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    stem = path.name.split(".")[0]
    return int(stem) if stem.isdigit() else payload.get("roundId")


def _round_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    value = item.get("round")
    if isinstance(value, bool) or not isinstance(value, int):
        return (0, str(value), item.get("source", ""))
    return (value, "", item.get("source", ""))


def _round_summary(discussion_dir: Path) -> dict[str, Any]:
    rounds_dir = discussion_dir / "rounds"
    final_paths = sorted(rounds_dir.glob("[0-9][0-9][0-9].json")) if rounds_dir.exists() else []
    partial_paths = sorted(rounds_dir.glob("*.json.partial")) if rounds_dir.exists() else []
    rounds: list[dict[str, Any]] = []
    for path in final_paths:
        payload, error = _load_json(path)
        if isinstance(payload, dict):
            validation = validate_round_file(path)
            rounds.append(
                {
                    "round": _round_value(payload, path),
                    "source": "final",
                    "path": str(path),
                    "messageCount": len(payload.get("messages", []) or []),
                    "validationOk": validation["ok"],
                }
            )
        elif error:
            rounds.append({"source": "final", "path": str(path), "error": error})
    for path in partial_paths:
        payload, error = _load_json(path)
        if isinstance(payload, dict):
            rounds.append(
                {
                    "round": _round_value(payload, path),
                    "source": "partial",
                    "path": str(path),
                    "phase": payload.get("phase"),
                    "messageCount": len(payload.get("messages", []) or []),
                }
            )
        elif error:
            rounds.append({"source": "partial", "path": str(path), "error": error})
    return {
        "finalCount": len(final_paths),
        "partialCount": len(partial_paths),
        "rounds": sorted(rounds, key=_round_sort_key),
    }


def _prompt_summary(discussion_dir: Path) -> dict[str, Any]:
    prompt_paths = sorted((discussion_dir / "prompts").glob("**/prompt-build.json"))
    phases: Counter[str] = Counter()
    personas: Counter[str] = Counter()
    visibility: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []
    artifacts: list[str] = []
    prompt_char_total = 0
    prompt_char_max = 0
    prompt_char_counted = 0
    for path in prompt_paths:
        payload, error = _load_json(path)
        artifacts.append(str(path))
        if error:
            errors.append(error)
            continue
        if not isinstance(payload, dict):
            errors.append(_issue("invalid_prompt_artifact", str(path), "prompt-build artifact must be an object"))
            continue
        phases[str(payload.get("phase") or "unknown")] += 1
        persona = payload.get("persona")
        if isinstance(persona, dict):
            personas[str(persona.get("id") or persona.get("name") or "unknown")] += 1
        for value in (payload.get("visibility") or {}).values():
            visibility[str(value)] += 1
        char_count = payload.get("promptCharCount")
        if isinstance(char_count, int) and not isinstance(char_count, bool):
            prompt_char_total += char_count
            prompt_char_max = max(prompt_char_max, char_count)
            prompt_char_counted += 1
    return {
        "count": len(prompt_paths),
        "promptBuildCount": len(prompt_paths),
        "phases": dict(sorted(phases.items())),
        "personas": dict(sorted(personas.items())),
        "visibility": dict(sorted(visibility.items())),
        "promptCharTotal": prompt_char_total,
        "promptCharMax": prompt_char_max,
        "promptCharCounted": prompt_char_counted,
        "errors": errors,
        "paths": artifacts,
    }


def _transport_summary(discussion_dir: Path) -> dict[str, Any]:
    transport_root = discussion_dir / "transport"
    spawn_paths = sorted(transport_root.glob("**/spawn-order.json"))
    wait_paths = sorted(transport_root.glob("**/wait-batches.jsonl"))
    collect_paths = sorted(transport_root.glob("**/collect-result.json"))
    errors: list[dict[str, Any]] = []
    collect_results: list[dict[str, Any]] = []

    wait_batch_count = 0
    for path in wait_paths:
        batches, batch_errors = _load_jsonl(path)
        wait_batch_count += len(batches)
        errors.extend(batch_errors)

    unreadable_collect_results = 0
    for path in collect_paths:
        payload, error = _load_json(path)
        if error:
            errors.append(error)
            unreadable_collect_results += 1
            continue
        if not isinstance(payload, dict):
            errors.append(_issue("invalid_collect_result", str(path), "collect result must be an object"))
            unreadable_collect_results += 1
            continue
        collect_results.append(
            {
                "path": str(path),
                "ok": bool(payload.get("ok")),
                "complete": bool(payload.get("complete")),
                "timedOut": bool(payload.get("timedOut") or payload.get("timed_out")),
                "missingAgentIds": payload.get("missingAgentIds") or [],
                "errorCount": len(payload.get("errors") or []),
                "resultCount": len(payload.get("results") or []),
            }
        )

    complete = (
        bool(collect_results)
        and unreadable_collect_results == 0
        and all(item["complete"] and item["ok"] and not item["timedOut"] for item in collect_results)
    )
    return {
        "spawnOrderCount": len(spawn_paths),
        "waitBatchCount": wait_batch_count,
        "collectResultCount": len(collect_results),
        "complete": complete,
        "collectResults": collect_results,
        "errors": errors,
        "paths": [str(path) for path in [*spawn_paths, *wait_paths, *collect_paths]],
    }


def _events_summary(discussion_dir: Path) -> dict[str, Any]:
    events, errors = _load_jsonl(discussion_dir / "events.jsonl")
    counts = Counter(event.get("type", "unknown") for event in events)
    first_ts = last_ts = None
    span_seconds: int | None = None
    stamps = [event.get("ts") for event in events if isinstance(event, dict) and isinstance(event.get("ts"), str)]
    if len(stamps) >= 2:
        from datetime import datetime

        try:
            start = datetime.strptime(stamps[0], "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.strptime(stamps[-1], "%Y-%m-%dT%H:%M:%SZ")
            first_ts, last_ts = stamps[0], stamps[-1]
            span_seconds = int((end - start).total_seconds())
        except (ValueError, TypeError):
            first_ts = last_ts = None
            span_seconds = None
    return {
        "count": len(events),
        "counts": dict(sorted(counts.items())),
        "last": events[-1] if events else None,
        "firstTs": first_ts,
        "lastTs": last_ts,
        "spanSeconds": span_seconds,
        "errors": errors,
    }


def _quality_summary(discussion_dir: Path) -> dict[str, Any]:
    round_files = sorted((discussion_dir / "rounds").glob("[0-9][0-9][0-9].json"))
    synthesis_present = (discussion_dir / "artifacts" / "synthesis.md").exists()
    latest_synthesis: dict[str, Any] = {}
    if round_files:
        payload, _error = _load_json(round_files[-1])
        if isinstance(payload, dict) and isinstance(payload.get("synthesis"), dict):
            latest_synthesis = payload["synthesis"]
    quality_score = latest_synthesis.get("qualityScore")
    recommendation = latest_synthesis.get("recommendation")
    return {
        "synthesisPresent": synthesis_present or bool(latest_synthesis),
        "qualityScore": quality_score,
        "recommendation": recommendation,
    }


def _capability_summary(discussion_dir: Path) -> dict[str, Any]:
    capability_dir = discussion_dir / "capabilities"
    discussion_profile_path = capability_dir / "profile.json"
    source = "discussion" if discussion_profile_path.exists() else "default"
    profile_path = discussion_profile_path if source == "discussion" else default_profile_path()
    profile, profile_error = _load_json(profile_path)
    if not isinstance(profile, dict):
        errors = [profile_error] if profile_error else [_issue("invalid_profile", str(profile_path), "profile must be an object")]
        return {
            "ok": False,
            "source": source,
            "profilePath": str(profile_path),
            "toolEvidencePath": None,
            "paths": [str(profile_path)],
            "errors": errors,
            "profile": {},
            "effective": {},
            "toolEvidence": {
                "recordCount": 0,
                "acceptedCount": 0,
                "citable": False,
                "accepted": [],
                "errors": errors,
            },
        }

    tool_evidence_path = capability_dir / "tool-evidence.jsonl"
    records = None
    tool_errors: list[dict[str, Any]] = []
    if tool_evidence_path.exists():
        records, tool_errors = load_tool_evidence_jsonl(tool_evidence_path)

    report = capability_doctor_report(
        profile,
        records,
        tool_evidence_base_dir=capability_dir if tool_evidence_path.exists() else None,
    )
    errors = [*tool_errors, *report.get("errors", [])]
    tool_evidence = dict(report.get("toolEvidence") or {})
    tool_evidence["errors"] = [*tool_errors, *tool_evidence.get("errors", [])]

    paths = [str(profile_path)]
    if tool_evidence_path.exists():
        paths.append(str(tool_evidence_path))
    for accepted in tool_evidence.get("accepted", []) or []:
        artifact_path = accepted.get("artifactPath")
        if isinstance(artifact_path, str) and artifact_path.strip():
            paths.append(str(capability_dir / artifact_path))

    return {
        "ok": not errors,
        "source": source,
        "profilePath": str(profile_path),
        "toolEvidencePath": str(tool_evidence_path) if tool_evidence_path.exists() else None,
        "paths": sorted(dict.fromkeys(paths)),
        "errors": errors,
        "profile": report.get("profile", {}),
        "effective": report.get("effective", {}),
        "toolEvidence": tool_evidence,
    }


def _artifact_paths(discussion_dir: Path) -> list[str]:
    if not discussion_dir.exists():
        return []
    ignored_parts = {"tmp"}
    paths = []
    for path in sorted(discussion_dir.rglob("*")):
        if path.is_file() and not any(part in ignored_parts for part in path.relative_to(discussion_dir).parts):
            paths.append(str(path))
    return paths


def _artifact_total_bytes(discussion_dir: Path) -> int:
    total = 0
    for path_str in _artifact_paths(discussion_dir):
        try:
            total += Path(path_str).stat().st_size
        except OSError:
            continue
    return total


def _next_action(
    validation: dict[str, Any],
    transport: dict[str, Any],
    resume: dict[str, Any],
    manifest: dict[str, Any],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    if not validation.get("ok", False):
        return {
            "kind": "inspect_validation",
            "command": "swarm-rt validate-discussion --dir <discussion-dir>",
            "reason": "discussion validation failed",
        }

    incomplete_collect = next(
        (
            item
            for item in transport.get("collectResults", [])
            if not item.get("complete") or not item.get("ok") or item.get("timedOut")
        ),
        None,
    )
    if incomplete_collect:
        return {
            "kind": "poll_remaining",
            "command": "swarm-rt collect-merge ...",
            "reason": "transport collect result is incomplete",
            "missingAgentIds": incomplete_collect.get("missingAgentIds", []),
        }

    if transport.get("errors"):
        return {
            "kind": "inspect_artifacts",
            "command": "swarm-rt adapter-smoke --dir <discussion-dir>",
            "reason": "transport artifacts are unreadable",
        }

    if not resume.get("ok", True):
        return {
            "kind": "inspect_artifacts",
            "command": "swarm-rt resume-plan --dir <discussion-dir>",
            "reason": "WAL state is unreadable",
        }

    if resume.get("source") == "partial":
        return {
            "kind": "resume_round",
            "command": "swarm-rt resume-plan --dir <discussion-dir>",
            "reason": "partial round is the current WAL state",
            "round": resume.get("round"),
            "phase": resume.get("phase"),
        }

    if not capabilities.get("ok", True):
        return {
            "kind": "inspect_capabilities",
            "command": "swarm-rt capability-doctor --profile <profile.json> --tool-evidence <tool-evidence.jsonl>",
            "reason": "capability profile or tool evidence is not citable",
            "errorCount": len(capabilities.get("errors") or []),
        }

    status = manifest.get("status")
    if status in {"completed", "complete", "done"} and resume.get("source") == "final":
        return {"kind": "none", "command": None, "reason": "discussion completed"}
    if resume.get("source") == "none":
        return {"kind": "start_round", "command": "swarm-rt append-message ...", "reason": "no round state exists"}
    return {"kind": "inspect_artifacts", "command": "swarm-rt trace --dir <discussion-dir>", "reason": "manual inspection needed"}


def _health(
    validation: dict[str, Any],
    transport: dict[str, Any],
    resume: dict[str, Any],
    next_action: dict[str, Any],
    capabilities: dict[str, Any],
) -> str:
    if not validation.get("ok", False):
        return "off-track"
    if not resume.get("ok", True):
        return "off-track"
    if not capabilities.get("ok", True):
        return "at-risk"
    if next_action.get("kind") in {"poll_remaining", "resume_round", "start_round", "inspect_artifacts"}:
        return "at-risk"
    if transport.get("errors") or resume.get("source") == "partial":
        return "at-risk"
    return "on-track"


def _relax_validation_for_partial(validation: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    if resume.get("source") != "partial":
        return validation

    errors = validation.get("errors", []) or []
    missing_rounds = [error for error in errors if error.get("code") == "missing_rounds"]
    remaining = [error for error in errors if error.get("code") != "missing_rounds"]
    if not missing_rounds:
        return validation

    relaxed = dict(validation)
    relaxed["errors"] = remaining
    relaxed["warnings"] = [
        *validation.get("warnings", []),
        *[
            {
                **error,
                "message": "committed round is absent because the current WAL source is partial",
            }
            for error in missing_rounds
        ],
    ]
    relaxed["ok"] = not remaining
    return relaxed


def build_trace(discussion_dir: Path) -> dict[str, Any]:
    if not discussion_dir.exists():
        return {
            "ok": False,
            "kind": TRACE_KIND,
            "errors": [_issue("missing_directory", str(discussion_dir), "discussion directory does not exist")],
        }
    if not discussion_dir.is_dir():
        return {
            "ok": False,
            "kind": TRACE_KIND,
            "errors": [_issue("invalid_directory", str(discussion_dir), "discussion path is not a directory")],
        }

    manifest, _manifest_errors = _manifest_summary(discussion_dir)
    validation = validate_discussion_dir(discussion_dir)

    resume = resume_plan(discussion_dir)
    validation = _relax_validation_for_partial(validation, resume)
    prompts = _prompt_summary(discussion_dir)
    transport = _transport_summary(discussion_dir)
    events = _events_summary(discussion_dir)
    rounds = _round_summary(discussion_dir)
    quality = _quality_summary(discussion_dir)
    capabilities = _capability_summary(discussion_dir)
    next_action = _next_action(validation, transport, resume, manifest, capabilities)
    return {
        "ok": True,
        "kind": TRACE_KIND,
        "discussionDir": str(discussion_dir),
        "discussion": {
            "id": manifest.get("id"),
            "title": manifest.get("title"),
            "mode": manifest.get("mode"),
            "status": manifest.get("status"),
            "schemaVersion": manifest.get("schemaVersion"),
        },
        "health": _health(validation, transport, resume, next_action, capabilities),
        "validation": validation,
        "resume": resume,
        "rounds": rounds,
        "prompts": prompts,
        "transport": transport,
        "capabilities": capabilities,
        "quality": quality,
        "events": events,
        "artifacts": {
            "root": str(discussion_dir),
            "paths": _artifact_paths(discussion_dir),
            "totalBytes": _artifact_total_bytes(discussion_dir),
        },
        "nextAction": next_action,
    }


def _outcome(trace: dict[str, Any]) -> dict[str, Any]:
    action = trace.get("nextAction", {})
    status = trace.get("discussion", {}).get("status")
    if action.get("kind") == "none":
        return {"result": "completed", "determinedBy": "discussion", "reason": "discussion completed", "nextAction": action}
    if action.get("kind") == "inspect_validation":
        return {"result": "failed", "determinedBy": "validation", "reason": "validation failed", "nextAction": action}
    if action.get("kind") == "poll_remaining":
        return {"result": "incomplete", "determinedBy": "transport", "reason": "transport incomplete", "nextAction": action}
    if action.get("kind") == "resume_round":
        return {"result": "incomplete", "determinedBy": "wal", "reason": "partial round present", "nextAction": action}
    if action.get("kind") == "inspect_capabilities":
        return {
            "result": "unverified",
            "determinedBy": "capabilities",
            "reason": action.get("reason"),
            "nextAction": action,
        }
    if action.get("kind") == "inspect_artifacts":
        return {"result": "unverified", "determinedBy": "trace", "reason": action.get("reason"), "nextAction": action}
    return {"result": status or "unknown", "determinedBy": "trace", "reason": action.get("reason"), "nextAction": action}


def _metrics(trace: dict[str, Any]) -> dict[str, Any]:
    artifacts = trace.get("artifacts", {}).get("paths", [])
    rounds = trace.get("rounds", {})
    tool_evidence = trace.get("capabilities", {}).get("toolEvidence", {})
    return {
        "artifactCount": len(artifacts),
        "promptBuildCount": trace.get("prompts", {}).get("count", 0),
        "collectResultCount": trace.get("transport", {}).get("collectResultCount", 0),
        "toolEvidenceRecordCount": tool_evidence.get("recordCount", 0),
        "citableToolEvidenceCount": tool_evidence.get("acceptedCount", 0)
        if tool_evidence.get("citable")
        else 0,
        "finalRoundCount": rounds.get("finalCount", 0),
        "partialRoundCount": rounds.get("partialCount", 0),
        "eventCount": trace.get("events", {}).get("count", 0),
        "validationErrorCount": len(trace.get("validation", {}).get("errors", []) or []),
        "promptCharTotal": trace.get("prompts", {}).get("promptCharTotal", 0),
        "promptCharMax": trace.get("prompts", {}).get("promptCharMax", 0),
        "artifactTotalBytes": trace.get("artifacts", {}).get("totalBytes", 0),
        "eventSpanSeconds": trace.get("events", {}).get("spanSeconds"),
    }


def build_evidence(discussion_dir: Path) -> dict[str, Any]:
    trace = build_trace(discussion_dir)
    if not trace.get("ok"):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "kind": EVIDENCE_KIND,
            "generatedAt": _now_iso(),
            "ok": False,
            "errors": trace.get("errors", []),
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "generatedAt": _now_iso(),
        "ok": True,
        "discussion": trace["discussion"],
        "outcome": _outcome(trace),
        "metrics": _metrics(trace),
        "validation": {
            "ok": trace["validation"].get("ok"),
            "errorCount": len(trace["validation"].get("errors", []) or []),
            "warningCount": len(trace["validation"].get("warnings", []) or []),
            "summary": trace["validation"].get("summary", {}),
        },
        "transport": {
            "complete": trace["transport"].get("complete"),
            "spawnOrderCount": trace["transport"].get("spawnOrderCount"),
            "waitBatchCount": trace["transport"].get("waitBatchCount"),
            "collectResultCount": trace["transport"].get("collectResultCount"),
            "collectResults": trace["transport"].get("collectResults", []),
        },
        "prompts": {
            "promptBuildCount": trace["prompts"].get("count"),
            "phases": trace["prompts"].get("phases", {}),
            "personas": trace["prompts"].get("personas", {}),
            "visibility": trace["prompts"].get("visibility", {}),
        },
        "capabilities": {
            "ok": trace["capabilities"].get("ok"),
            "source": trace["capabilities"].get("source"),
            "profilePath": trace["capabilities"].get("profilePath"),
            "toolEvidencePath": trace["capabilities"].get("toolEvidencePath"),
            "profile": trace["capabilities"].get("profile", {}),
            "effective": trace["capabilities"].get("effective", {}),
            "toolEvidence": {
                "recordCount": trace["capabilities"].get("toolEvidence", {}).get("recordCount", 0),
                "acceptedCount": trace["capabilities"].get("toolEvidence", {}).get("acceptedCount", 0),
                "citable": trace["capabilities"].get("toolEvidence", {}).get("citable", False),
                "accepted": trace["capabilities"].get("toolEvidence", {}).get("accepted", []),
                "errorCount": len(trace["capabilities"].get("errors") or []),
            },
            "paths": trace["capabilities"].get("paths", []),
        },
        "wal": {
            "resume": trace["resume"],
            "rounds": trace["rounds"],
            "events": {
                "count": trace["events"].get("count"),
                "counts": trace["events"].get("counts", {}),
                "lastType": (trace["events"].get("last") or {}).get("type"),
            },
        },
        "quality": trace["quality"],
        "trace": {
            "health": trace["health"],
            "nextAction": trace["nextAction"],
        },
        "artifacts": trace["artifacts"],
        "rawHostLogs": _raw_host_logs(discussion_dir),
    }


def _raw_host_logs(discussion_dir: Path) -> dict[str, Any]:
    paths = (
        [str(path) for path in sorted(discussion_dir.glob("host-logs/**/*")) if path.is_file()]
        if discussion_dir.exists()
        else []
    )
    return {"required": False, "present": bool(paths), "paths": paths}
