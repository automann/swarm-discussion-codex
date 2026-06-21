"""Projected custom-agent provenance gate (plan 008 / ADR 0001 D4).

Opt-in: the consistency checks fire only when a transport phase declares
``host-step.transport.customAgentProjection.projected == true``. A non-projected
discussion is inert here, so the v0.2.x path is unaffected. With
``require_projection=True`` it additionally rejects a discussion that declares no
projection at all — the v0.3.0 release mode that stops an adapter certifying the
old spawn path while its docs claim the projected topology.

The runtime owns and validates the SHAPE and run-scoped naming; it cannot see
the host agent directory, so actual file deletion is proven by the adapter's
zero-residue release gate, not here (ADR 0001 Q4).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}\Z")


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _load_json(path: Path) -> tuple[Any, dict[str, Any] | None]:
    try:
        return json.loads(path.read_text()), None
    except OSError as exc:
        return None, _issue("unreadable_file", str(path), f"cannot read file: {exc}")
    except json.JSONDecodeError as exc:
        return None, _issue("invalid_json", str(path), f"invalid JSON: {exc}")


def _safe_under(discussion_dir: Path, rel: Any) -> Path | None:
    """Resolve a relative path strictly under discussion_dir, or None if unsafe.

    Rejects non-strings, backslashes, absolute paths, and empty/'.'/'..' segments
    so a descriptor can never point certification evidence outside the discussion
    artifact tree (an absolute promptRef would otherwise ignore discussion_dir).
    """
    if not isinstance(rel, str) or not rel.strip():
        return None
    if "\\" in rel:
        return None
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return discussion_dir / rel


def validate_projection(discussion_dir: Path, require_projection: bool = False) -> dict[str, Any]:
    """Validate projected custom-agent provenance across a discussion's transport phases."""
    errors: list[dict[str, Any]] = []
    projected_phases = 0
    descriptor_names: set[str] = set()
    descriptor_path_sha: dict[str, Any] = {}

    transport_root = discussion_dir / "transport"
    host_steps = sorted(transport_root.glob("r*/*/host-step.json")) if transport_root.exists() else []

    for host_step_path in host_steps:
        host_step, load_error = _load_json(host_step_path)
        if load_error:
            errors.append(load_error)
            continue
        transport = host_step.get("transport") if isinstance(host_step, dict) else None
        projection = transport.get("customAgentProjection") if isinstance(transport, dict) else None
        if not (isinstance(projection, dict) and projection.get("projected") is True):
            continue  # phase not projected -> inert

        projected_phases += 1
        base = f"{host_step_path}:transport.customAgentProjection"
        count = projection.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            errors.append(_issue("invalid_custom_agent_projection", f"{base}.count", "count must be >= 1 when projected", count))
        source_dir = projection.get("agentSourceDir")
        if not (isinstance(source_dir, str) and source_dir.strip()):
            errors.append(_issue("invalid_custom_agent_projection", f"{base}.agentSourceDir", "agentSourceDir is required when projected"))

        collect_path = host_step_path.parent / "collect-result.json"
        if not collect_path.exists():
            errors.append(_issue("missing_collect_result", str(collect_path), "projected phase requires collect-result.json"))
            continue
        collect, collect_error = _load_json(collect_path)
        if collect_error:
            errors.append(collect_error)
            continue
        results = collect.get("results") if isinstance(collect, dict) else None
        for index, result in enumerate(results or []):
            where = f"{collect_path}:results[{index}]"
            descriptor = result.get("agentDescriptor") if isinstance(result, dict) else None
            if not isinstance(descriptor, dict):
                errors.append(_issue("missing_agent_descriptor", where, "projected discussion requires agentDescriptor on every result"))
                continue
            name = descriptor.get("projectedName")
            if not (isinstance(name, str) and name.strip()):
                errors.append(_issue("missing_agent_descriptor", f"{where}.projectedName", "projectedName is required"))
            else:
                descriptor_names.add(name)
            sha = descriptor.get("projectedSha256")
            sha_ok = isinstance(sha, str) and bool(_SHA256.match(sha))
            if not sha_ok:
                errors.append(_issue("invalid_projected_sha", f"{where}.projectedSha256", "projectedSha256 must be 64 lowercase hex characters", sha))
            prompt_ref = descriptor.get("promptRef")
            resolved_prompt = (
                _safe_under(discussion_dir, prompt_ref)
                if isinstance(prompt_ref, str) and prompt_ref.startswith("prompts/")
                else None
            )
            if resolved_prompt is None or not resolved_prompt.is_file():
                errors.append(
                    _issue(
                        "unresolved_prompt_ref",
                        f"{where}.promptRef",
                        "promptRef must be a relative path under prompts/ that resolves to an existing artifact in the discussion",
                        prompt_ref,
                    )
                )
            projected_path = descriptor.get("projectedPath")
            if not (isinstance(projected_path, str) and projected_path.strip()):
                errors.append(_issue("missing_agent_descriptor", f"{where}.projectedPath", "projectedPath is required when projection is declared"))
            else:
                descriptor_path_sha[projected_path] = sha if sha_ok else None

    if require_projection and projected_phases == 0:
        errors.append(
            _issue(
                "projection_required",
                str(discussion_dir),
                "discussion declares no projected custom agents (no host-step transport.customAgentProjection.projected == true)",
            )
        )

    if projected_phases > 0:
        manifest_path = discussion_dir / "projection-manifest.json"
        if not manifest_path.exists():
            errors.append(_issue("missing_projection_manifest", str(manifest_path), "projected discussion requires projection-manifest.json"))
        else:
            manifest, manifest_error = _load_json(manifest_path)
            if manifest_error:
                errors.append(manifest_error)
            elif not isinstance(manifest, dict):
                errors.append(_issue("invalid_projection_manifest", str(manifest_path), "projection manifest must be an object"))
            else:
                run_id = manifest.get("runId")
                if not (isinstance(run_id, str) and run_id.strip()):
                    errors.append(_issue("invalid_projection_manifest", f"{manifest_path}:runId", "runId is required"))
                    run_id = None
                if "deletionStatus" not in manifest:
                    errors.append(_issue("invalid_projection_manifest", f"{manifest_path}:deletionStatus", "deletionStatus is required"))
                created = {
                    entry.get("path"): entry.get("sha256")
                    for entry in (manifest.get("createdPaths") or [])
                    if isinstance(entry, dict)
                }
                for projected_path, descriptor_sha in sorted(descriptor_path_sha.items()):
                    if projected_path not in created:
                        errors.append(_issue("projection_manifest_mismatch", str(manifest_path), "descriptor projectedPath is not in manifest createdPaths", projected_path))
                    elif descriptor_sha is not None and created[projected_path] != descriptor_sha:
                        errors.append(
                            _issue(
                                "projection_manifest_mismatch",
                                str(manifest_path),
                                "descriptor projectedSha256 does not match manifest createdPaths sha256",
                                {"projectedPath": projected_path, "descriptorSha256": descriptor_sha, "manifestSha256": created[projected_path]},
                            )
                        )
                if run_id is not None:
                    for name in sorted(descriptor_names):
                        if run_id not in name:
                            errors.append(
                                _issue(
                                    "non_run_scoped_agent_name",
                                    str(manifest_path),
                                    "projectedName must embed the manifest runId (anti cross-run contamination)",
                                    {"projectedName": name, "runId": run_id},
                                )
                            )

    return {
        "ok": not errors,
        "errors": errors,
        "summary": {"projectedPhases": projected_phases, "projectedAgents": sorted(descriptor_names)},
    }
