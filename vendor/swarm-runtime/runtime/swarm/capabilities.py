"""Capability profile validation and evidence citation checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PROFILE_KIND = "swarm.capability_profile"
TOOL_EVIDENCE_KIND = "swarm.tool_evidence"
DEFAULT_PROFILE_ID = "expert-basic"
ORDINARY_EXPERT_ROLES = {"ordinary-expert", "expert"}
BROAD_TOOLS = {"bash", "edit", "write"}
READONLY_TOOLS = {"read", "glob", "grep"}
KNOWN_TOOLS = BROAD_TOOLS | READONLY_TOOLS


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def default_profile_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / "profiles" / "expert-basic.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(_issue("invalid_jsonl", f"{path}:{line_number}", f"invalid JSONL: {exc}"))
            continue
        if isinstance(payload, dict):
            records.append(payload)
        else:
            errors.append(_issue("invalid_tool_evidence", f"{path}:{line_number}", "record must be a JSON object"))
    return records, errors


def _string_list(value: Any, path: str, errors: list[dict[str, Any]]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(_issue("invalid_string_list", path, "must be a list of non-empty strings"))
        return []
    return value


def validate_capability_profile(profile: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        return {"ok": False, "errors": [_issue("invalid_profile", "profile", "profile must be an object")]}

    if profile.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(
            _issue(
                "unsupported_schema_version",
                "profile.schemaVersion",
                f"must be {SCHEMA_VERSION}",
                profile.get("schemaVersion"),
            )
        )
    if profile.get("kind") != PROFILE_KIND:
        errors.append(_issue("invalid_kind", "profile.kind", f"must be {PROFILE_KIND}", profile.get("kind")))

    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        errors.append(_issue("missing_string", "profile.id", "must be a non-empty string"))
        profile_id = ""

    for field in ("title", "status"):
        value = profile.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(_issue("missing_string", f"profile.{field}", "must be a non-empty string"))

    role = profile.get("role")
    if role not in ORDINARY_EXPERT_ROLES | {"coordinator", "executor"}:
        errors.append(_issue("invalid_role", "profile.role", "unknown capability role", role))

    default = profile.get("default", False)
    if not isinstance(default, bool):
        errors.append(_issue("invalid_boolean", "profile.default", "must be boolean"))
        default = False

    allowed_tools = _string_list(profile.get("allowedTools"), "profile.allowedTools", errors)
    unknown_tools = sorted(set(allowed_tools) - KNOWN_TOOLS)
    for tool in unknown_tools:
        errors.append(_issue("unknown_tool", "profile.allowedTools", "tool is not recognized", tool))

    broad_tools = sorted(set(allowed_tools) & BROAD_TOOLS)
    ordinary_expert = role in ORDINARY_EXPERT_ROLES
    if default and profile_id != DEFAULT_PROFILE_ID:
        errors.append(_issue("invalid_default_profile", "profile.id", "only expert-basic may be default", profile_id))
    if default and allowed_tools:
        errors.append(
            _issue(
                "default_profile_tools",
                "profile.allowedTools",
                "default expert profile must not grant tools",
                allowed_tools,
            )
        )
    if ordinary_expert and broad_tools:
        errors.append(
            _issue(
                "broad_tool_access",
                "profile.allowedTools",
                "ordinary experts must not receive broad tools",
                broad_tools,
            )
        )

    policy = profile.get("toolEvidencePolicy", {})
    if not isinstance(policy, dict):
        errors.append(_issue("invalid_policy", "profile.toolEvidencePolicy", "must be an object"))
        policy = {}
    for field in ("requiresLoggedToolCall", "requiresValidation"):
        if policy.get(field) is not True:
            errors.append(_issue("weak_evidence_policy", f"profile.toolEvidencePolicy.{field}", "must be true"))
    citation = policy.get("citation")
    if not isinstance(citation, str) or not citation.strip():
        errors.append(
            _issue("missing_string", "profile.toolEvidencePolicy.citation", "must be a non-empty string")
        )

    summary = {
        "id": profile_id,
        "role": role,
        "default": default,
        "allowedTools": allowed_tools,
        "broadTools": broad_tools,
        "readonlyTools": sorted(set(allowed_tools) & READONLY_TOOLS),
        "ordinaryExpert": ordinary_expert,
        "toolEvidencePolicy": {
            "requiresLoggedToolCall": policy.get("requiresLoggedToolCall") is True,
            "requiresValidation": policy.get("requiresValidation") is True,
        },
    }
    return {"ok": not errors, "errors": errors, "summary": summary}


def validate_tool_evidence_records(
    profile: dict[str, Any],
    records: list[dict[str, Any]],
    base_dir: Path | None = None,
) -> dict[str, Any]:
    profile_result = validate_capability_profile(profile)
    active_profile_id = profile_result.get("summary", {}).get("id")
    allowed_tools = set(profile_result.get("summary", {}).get("allowedTools", []))
    profile_errors = list(profile_result["errors"])
    record_errors: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        path = f"toolEvidence[{index}]"
        errors_before = len(record_errors)
        if record.get("schemaVersion") != SCHEMA_VERSION:
            record_errors.append(_issue("unsupported_schema_version", f"{path}.schemaVersion", f"must be {SCHEMA_VERSION}"))
        if record.get("kind") != TOOL_EVIDENCE_KIND:
            record_errors.append(_issue("invalid_kind", f"{path}.kind", f"must be {TOOL_EVIDENCE_KIND}", record.get("kind")))
        if record.get("profileId") != active_profile_id:
            record_errors.append(
                _issue(
                    "profile_mismatch",
                    f"{path}.profileId",
                    "tool evidence profileId must match the active profile",
                    record.get("profileId"),
                )
            )
        tool = record.get("tool")
        if tool not in allowed_tools:
            record_errors.append(_issue("tool_not_allowed", f"{path}.tool", "tool is not allowed by effective profile", tool))
        if record.get("validated") is not True:
            record_errors.append(_issue("unvalidated_tool_evidence", f"{path}.validated", "tool evidence must be validated"))
        artifact_path = record.get("artifactPath")
        if not isinstance(artifact_path, str) or not artifact_path.strip():
            record_errors.append(_issue("missing_artifact_path", f"{path}.artifactPath", "artifact path is required"))
        elif base_dir:
            resolved = base_dir / artifact_path
            if not resolved.exists():
                record_errors.append(
                    _issue(
                        "missing_artifact",
                        f"{path}.artifactPath",
                        "referenced tool artifact does not exist",
                        artifact_path,
                    )
                )
        validation = record.get("validation")
        if not isinstance(validation, dict) or validation.get("ok") is not True:
            record_errors.append(_issue("failed_tool_validation", f"{path}.validation", "validation.ok must be true"))
        if not profile_errors and len(record_errors) == errors_before:
            accepted.append(
                {
                    "agentId": record.get("agentId"),
                    "tool": tool,
                    "artifactPath": artifact_path,
                    "summary": record.get("summary", ""),
                }
            )

    errors = [*profile_errors, *record_errors]
    return {
        "ok": not errors,
        "errors": errors,
        "recordCount": len(records),
        "acceptedCount": len(accepted),
        "citable": bool(records) and not errors,
        "accepted": accepted,
    }


def capability_doctor_report(
    profile: dict[str, Any],
    tool_evidence_records: list[dict[str, Any]] | None = None,
    tool_evidence_base_dir: Path | None = None,
) -> dict[str, Any]:
    profile_result = validate_capability_profile(profile)
    evidence = None
    if tool_evidence_records is not None:
        evidence = validate_tool_evidence_records(profile, tool_evidence_records, base_dir=tool_evidence_base_dir)
    effective = dict(profile_result.get("summary", {}))
    effective["canCiteToolDerivedEvidence"] = bool(evidence and evidence.get("citable"))
    effective["citationRule"] = "tool evidence must be logged, validated, and allowed by the active profile"
    # evidence["errors"] already includes the profile errors; do not double-count.
    errors = list(evidence["errors"]) if evidence is not None else list(profile_result["errors"])
    return {
        "ok": not errors,
        "errors": errors,
        "profile": profile_result.get("summary", {}),
        "effective": effective,
        "toolEvidence": evidence
        or {
            "recordCount": 0,
            "acceptedCount": 0,
            "citable": False,
            "accepted": [],
            "errors": [],
        },
    }
