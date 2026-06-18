"""End-to-end fixture validation for the minimal discussion loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from swarm.adapter import validate_host_transport_metadata
from swarm.audit import EVIDENCE_KIND, build_evidence, build_trace
from swarm.validation import validate_discussion_dir

REQUIRED_EVIDENCE_KEYS = (
    "schemaVersion",
    "kind",
    "discussion",
    "outcome",
    "metrics",
    "validation",
    "transport",
    "prompts",
    "capabilities",
    "wal",
    "quality",
    "trace",
    "artifacts",
    "rawHostLogs",
)


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _load_json(path: Path) -> tuple[Any | None, dict[str, Any] | None]:
    import json

    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, _issue("missing_file", str(path), f"missing file: {path}")
    except json.JSONDecodeError as exc:
        return None, _issue("invalid_json", str(path), f"invalid JSON: {exc}")


def _host_step_reports(discussion_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    host_step_paths = sorted((discussion_dir / "transport").glob("**/host-step.json"))
    if not host_step_paths:
        errors.append(
            _issue(
                "missing_host_step",
                str(discussion_dir / "transport"),
                "minimal loop requires at least one host-step.json",
            )
        )
    for path in host_step_paths:
        payload, load_error = _load_json(path)
        if load_error:
            errors.append(load_error)
            continue
        result = validate_host_transport_metadata(payload)
        reports.append({"path": str(path), **result})
        if not result["ok"]:
            errors.extend(result["errors"])
    return reports, errors


def validate_minimal_loop(discussion_dir: Path) -> dict[str, Any]:
    """Validate that a fixture proves the smallest complete v2 runtime loop."""

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

    directory_validation = validate_discussion_dir(discussion_dir)
    if not directory_validation["ok"]:
        errors.extend(directory_validation["errors"])

    trace = build_trace(discussion_dir)
    evidence = build_evidence(discussion_dir)
    if not trace.get("ok"):
        errors.extend(trace.get("errors", []))
    if not evidence.get("ok"):
        errors.extend(evidence.get("errors", []))

    host_steps, host_errors = _host_step_reports(discussion_dir)
    errors.extend(host_errors)

    prompt_count = trace.get("prompts", {}).get("count", 0)
    if prompt_count < 1:
        errors.append(_issue("missing_prompt_artifact", "prompts", "minimal loop requires prompt-build artifacts"))

    transport = trace.get("transport", {})
    if not transport.get("complete"):
        errors.append(_issue("incomplete_transport", "transport", "minimal loop transport must be complete"))
    if transport.get("collectResultCount", 0) < 1:
        errors.append(_issue("missing_collect_result", "transport", "minimal loop requires collect-result.json"))

    capabilities = trace.get("capabilities", {})
    if not capabilities.get("ok"):
        errors.extend(capabilities.get("errors") or [])

    rounds = trace.get("rounds", {})
    if rounds.get("finalCount", 0) < 1:
        errors.append(_issue("missing_final_round", "rounds", "minimal loop requires a finalized round"))

    event_counts = trace.get("events", {}).get("counts", {})
    if event_counts.get("round_finalized", 0) < 1:
        errors.append(_issue("missing_finalization_event", "events.jsonl", "minimal loop requires round_finalized event"))

    required_artifacts = {
        "synthesis": discussion_dir / "artifacts" / "synthesis.md",
        "trace": discussion_dir / "artifacts" / "trace.json",
        "evidence": discussion_dir / "artifacts" / "evidence.json",
    }
    for label, path in required_artifacts.items():
        if not path.exists():
            errors.append(_issue("missing_loop_artifact", str(path), f"missing {label} artifact"))

    evidence_path = required_artifacts["evidence"]
    if evidence_path.exists():
        stored_evidence, evidence_error = _load_json(evidence_path)
        if evidence_error:
            errors.append(evidence_error)
        elif not isinstance(stored_evidence, dict):
            errors.append(_issue("invalid_evidence_artifact", str(evidence_path), "evidence artifact must be an object"))
        else:
            if stored_evidence.get("kind") != EVIDENCE_KIND:
                errors.append(
                    _issue(
                        "invalid_evidence_artifact",
                        str(evidence_path),
                        f"evidence artifact kind must be {EVIDENCE_KIND}",
                        stored_evidence.get("kind"),
                    )
                )
            missing_keys = [key for key in REQUIRED_EVIDENCE_KEYS if key not in stored_evidence]
            if missing_keys:
                errors.append(
                    _issue(
                        "incomplete_evidence_artifact",
                        str(evidence_path),
                        "evidence artifact is missing schema-required keys",
                        missing_keys,
                    )
                )

    next_action = trace.get("nextAction", {})
    if trace.get("health") != "on-track" or next_action.get("kind") != "none":
        errors.append(
            _issue(
                "loop_not_complete",
                "trace",
                "minimal loop must be on-track with no next action",
                {"health": trace.get("health"), "nextAction": next_action},
            )
        )

    return {
        "ok": not errors,
        "errors": errors,
        "summary": {
            "discussionId": trace.get("discussion", {}).get("id"),
            "health": trace.get("health"),
            "hostStepCount": len(host_steps),
            "promptBuildCount": prompt_count,
            "collectResultCount": transport.get("collectResultCount", 0),
            "finalRoundCount": rounds.get("finalCount", 0),
            "capabilityProfile": capabilities.get("profile", {}).get("id"),
            "citableToolEvidence": capabilities.get("toolEvidence", {}).get("citable", False),
            "staticTraceArtifact": str(required_artifacts["trace"]),
            "staticEvidenceArtifact": str(required_artifacts["evidence"]),
        },
        "validation": directory_validation,
        "hostSteps": host_steps,
        "trace": {
            "health": trace.get("health"),
            "nextAction": next_action,
        },
        "evidence": {
            "outcome": evidence.get("outcome"),
            "metrics": evidence.get("metrics"),
        },
    }
