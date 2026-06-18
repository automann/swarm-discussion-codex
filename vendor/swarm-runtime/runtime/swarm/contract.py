"""Runtime/plugin package boundary contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm import planned_commands

SCHEMA_VERSION = 1
CONTRACT_KIND = "swarm.runtime_contract"
REQUIRED_PLUGIN_COMMANDS = {
    "context-build",
    "prompt-build",
    "collect-merge",
    "transport-init",
    "transport-append-batch",
    "transport-collect",
    "append-message",
    "checkpoint",
    "finalize-round",
    "trace",
    "evidence",
    "validate-host-step",
    "adapter-smoke",
    "validate-loop",
}
REQUIRED_INTEGRATION_GATES = {"validate-host-step", "adapter-smoke", "validate-loop"}
FORBIDDEN_RUNTIME_RESPONSIBILITIES = {
    "spawn-host-agents",
    "wait-host-agents",
    "parent-conversation-orchestration",
    "plugin-installation",
    "marketplace-management",
}


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def default_contract_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / "runtime-contract.json"


def load_runtime_contract(path: Path | None = None) -> dict[str, Any]:
    contract_path = path or default_contract_path()
    return json.loads(contract_path.read_text())


def _as_mapping(value: Any, path: str, errors: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(_issue("invalid_mapping", path, "must be a JSON object"))
        return {}
    return value


def _as_list(value: Any, path: str, errors: list[dict[str, Any]]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(_issue("invalid_list", path, "must be a list"))
        return []
    return value


def _string_set(value: Any, path: str, errors: list[dict[str, Any]]) -> set[str]:
    items = _as_list(value, path, errors)
    strings: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            errors.append(_issue("invalid_string", f"{path}[{index}]", "must be a non-empty string", item))
            continue
        strings.add(item)
    return strings


def validate_runtime_contract(contract: Any) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(contract, dict):
        return {"ok": False, "errors": [_issue("invalid_contract", "contract", "contract must be an object")]}

    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(
            _issue(
                "unsupported_schema_version",
                "schemaVersion",
                f"must be {SCHEMA_VERSION}",
                contract.get("schemaVersion"),
            )
        )
    if contract.get("kind") != CONTRACT_KIND:
        errors.append(_issue("invalid_kind", "kind", f"must be {CONTRACT_KIND}", contract.get("kind")))

    runtime = _as_mapping(contract.get("runtime"), "runtime", errors)
    if runtime.get("name") != "swarm-discussion-runtime":
        errors.append(_issue("invalid_runtime_name", "runtime.name", "unexpected runtime name", runtime.get("name")))
    if not isinstance(runtime.get("compatibility"), str) or not runtime.get("compatibility"):
        errors.append(_issue("missing_compatibility", "runtime.compatibility", "compatibility is required"))

    commands = _as_mapping(contract.get("commands"), "commands", errors)
    command_names = set(commands)
    missing_commands = sorted(REQUIRED_PLUGIN_COMMANDS - command_names)
    for command in missing_commands:
        errors.append(_issue("missing_required_command", f"commands.{command}", "required plugin command is missing"))

    planned = set(planned_commands())
    adapter_flagged: set[str] = set()
    for name, spec in commands.items():
        path = f"commands.{name}"
        if name not in planned:
            errors.append(_issue("unknown_command", path, "command is not in planned runtime command surface", name))
        if not isinstance(spec, dict):
            errors.append(_issue("invalid_command_spec", path, "command spec must be an object"))
            continue
        if spec.get("owner") != "runtime":
            errors.append(_issue("invalid_command_owner", f"{path}.owner", "runtime contract commands must be runtime-owned", spec.get("owner")))
        if spec.get("stability") != "contract":
            errors.append(_issue("invalid_command_stability", f"{path}.stability", "stable plugin commands must be contract"))
        for field in ("adapterFacing", "mutatesState"):
            if not isinstance(spec.get(field), bool):
                errors.append(_issue("invalid_boolean", f"{path}.{field}", "must be boolean", spec.get(field)))
        if spec.get("adapterFacing") is True:
            adapter_flagged.add(name)
        _string_set(spec.get("produces", []), f"{path}.produces", errors)
        responsibilities = _string_set(spec.get("responsibilities"), f"{path}.responsibilities", errors)
        overlap = sorted(responsibilities & FORBIDDEN_RUNTIME_RESPONSIBILITIES)
        for responsibility in overlap:
            errors.append(
                _issue(
                    "forbidden_command_responsibility",
                    f"{path}.responsibilities",
                    "command claims a host/plugin responsibility",
                    responsibility,
                )
            )

    adapter_facing = _string_set(contract.get("adapterFacingCommands"), "adapterFacingCommands", errors)
    for command in sorted(adapter_flagged - adapter_facing):
        errors.append(
            _issue(
                "adapter_facing_mismatch",
                f"commands.{command}.adapterFacing",
                "command is flagged adapterFacing but missing from adapterFacingCommands",
                command,
            )
        )
    for command in sorted((adapter_facing & set(commands)) - adapter_flagged):
        errors.append(
            _issue(
                "adapter_facing_mismatch",
                "adapterFacingCommands",
                "command is listed adapter-facing but its spec is not flagged adapterFacing",
                command,
            )
        )
    missing_adapter_commands = sorted(REQUIRED_INTEGRATION_GATES - adapter_facing)
    for command in missing_adapter_commands:
        errors.append(_issue("missing_adapter_facing_command", "adapterFacingCommands", "adapter gate is not adapter-facing", command))
    for command in sorted(adapter_facing - command_names):
        errors.append(_issue("unknown_adapter_facing_command", "adapterFacingCommands", "adapter-facing command is not declared", command))

    gates = _string_set(contract.get("integrationGates"), "integrationGates", errors)
    for command in sorted(REQUIRED_INTEGRATION_GATES - gates):
        errors.append(_issue("missing_integration_gate", "integrationGates", "required integration gate is missing", command))
    for command in sorted(gates - adapter_facing):
        errors.append(_issue("gate_not_adapter_facing", "integrationGates", "integration gate must be adapter-facing", command))

    boundaries = _as_mapping(contract.get("boundaries"), "boundaries", errors)
    for owner in ("skillPrompt", "hostAdapter", "runtime"):
        owner_spec = _as_mapping(boundaries.get(owner), f"boundaries.{owner}", errors)
        _string_set(owner_spec.get("responsibilities", []), f"boundaries.{owner}.responsibilities", errors)
        _string_set(owner_spec.get("forbidden", []), f"boundaries.{owner}.forbidden", errors)

    runtime_spec = boundaries.get("runtime", {}) if isinstance(boundaries.get("runtime"), dict) else {}
    runtime_responsibilities = set(runtime_spec.get("responsibilities") or [])
    runtime_forbidden = set(runtime_spec.get("forbidden") or [])
    for responsibility in sorted(runtime_responsibilities & FORBIDDEN_RUNTIME_RESPONSIBILITIES):
        errors.append(
            _issue(
                "forbidden_runtime_responsibility",
                "boundaries.runtime.responsibilities",
                "runtime boundary includes a host/plugin responsibility",
                responsibility,
            )
        )
    missing_forbidden = sorted(FORBIDDEN_RUNTIME_RESPONSIBILITIES - runtime_forbidden)
    for responsibility in missing_forbidden:
        errors.append(
            _issue(
                "missing_runtime_forbidden_responsibility",
                "boundaries.runtime.forbidden",
                "runtime boundary must explicitly forbid this responsibility",
                responsibility,
            )
        )

    declared_forbidden = _string_set(
        contract.get("forbiddenRuntimeResponsibilities"), "forbiddenRuntimeResponsibilities", errors
    )
    for responsibility in sorted(FORBIDDEN_RUNTIME_RESPONSIBILITIES - declared_forbidden):
        errors.append(
            _issue(
                "missing_forbidden_responsibility",
                "forbiddenRuntimeResponsibilities",
                "contract must declare this forbidden runtime responsibility",
                responsibility,
            )
        )

    artifacts = _as_list(contract.get("stableArtifacts"), "stableArtifacts", errors)
    artifact_paths = {
        item.get("path")
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    for path in (
        "context/summary.md",
        "prompts/r<round>/<phase>/<agent>/prompt-build.json",
        "transport/r<round>/<phase>/host-step.json",
        "transport/r<round>/<phase>/collect-result.json",
        "rounds/<round>.json",
        "artifacts/evidence.json",
    ):
        if path not in artifact_paths:
            errors.append(_issue("missing_stable_artifact", "stableArtifacts", "stable artifact path is missing", path))

    return {
        "ok": not errors,
        "errors": errors,
        "summary": {
            "contractId": contract.get("contractId"),
            "compatibility": runtime.get("compatibility"),
            "commandCount": len(commands),
            "adapterFacingCommands": sorted(adapter_facing),
            "integrationGates": sorted(gates),
            "stableArtifactCount": len(artifact_paths),
        },
    }
