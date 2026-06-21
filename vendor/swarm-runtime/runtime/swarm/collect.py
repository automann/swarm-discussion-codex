"""Fan-in merge helpers for host wait results."""

from __future__ import annotations

import json
from typing import Any


def _agent_id(spec: dict[str, Any]) -> str | None:
    value = spec.get("agentId") or spec.get("agent_id")
    return str(value) if value is not None else None


def _persona(spec: dict[str, Any]) -> str | None:
    value = spec.get("persona") or spec.get("name")
    return str(value) if value is not None else None


def _parse_completed(entry: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(entry, dict):
        return None, "status entry is not an object"
    if "completed" not in entry:
        return None, f"agent did not complete; status keys={sorted(entry)}"

    raw = entry["completed"]
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return None, "completed payload is neither JSON string nor object"

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"unparseable completed payload: {exc}"
    if not isinstance(payload, dict):
        return None, "completed payload JSON is not an object"
    return payload, None


def collect_merge(
    spawn_order: list[dict[str, Any]], wait_results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Merge wait batches and return completed persona payloads in spawn order."""

    status_by_agent: dict[str, Any] = {}
    timed_out = False
    errors: list[dict[str, Any]] = []
    missing = object()

    for batch_index, wait_result in enumerate(wait_results, start=1):
        if not isinstance(wait_result, dict):
            errors.append(
                {
                    "code": "invalid_wait_result",
                    "batch": batch_index,
                    "message": "wait result is not an object",
                }
            )
            continue

        timed_out = timed_out or bool(
            wait_result.get("timed_out") or wait_result.get("timedOut")
        )
        status = wait_result.get("status", {})
        if status is None:
            status = {}
        elif not isinstance(status, dict):
            errors.append(
                {
                    "code": "invalid_status",
                    "batch": batch_index,
                    "message": "wait result status is not an object",
                }
            )
            continue

        for agent_id, entry in status.items():
            agent_id = str(agent_id)
            previous = status_by_agent.get(agent_id, missing)
            if previous is not missing:
                previous_payload, previous_error = _parse_completed(previous)
                next_payload, next_error = _parse_completed(entry)
                if previous_error is None and next_error is not None:
                    continue
                if previous_error is None and next_error is None and previous_payload != next_payload:
                    errors.append(
                        {
                            "code": "conflicting_completed_payload",
                            "batch": batch_index,
                            "agentId": agent_id,
                            "message": "agent reported two different completed payloads",
                        }
                    )
            status_by_agent[agent_id] = entry

    parsed_by_agent = {
        agent_id: _parse_completed(entry)[0]
        for agent_id, entry in status_by_agent.items()
    }
    results: list[dict[str, Any]] = []
    missing_agent_ids: list[str | None] = []
    missing_personas: list[str | None] = []
    consumed = {
        _agent_id(spec) for spec in spawn_order if _agent_id(spec) in status_by_agent
    }

    for spec in spawn_order:
        expected_agent_id = _agent_id(spec)
        persona = _persona(spec)
        entry = status_by_agent.get(expected_agent_id)
        actual_agent_id = expected_agent_id

        if entry is None:
            token = spec.get("token")
            matches = [
                candidate_agent_id
                for candidate_agent_id, payload in parsed_by_agent.items()
                if candidate_agent_id not in consumed
                and payload
                and (
                    payload.get("name") == persona
                    or payload.get("persona") == persona
                    or (token and payload.get("token") == token)
                )
            ]
            if not matches:
                missing_agent_ids.append(expected_agent_id)
                missing_personas.append(persona)
                continue
            if len(matches) > 1:
                errors.append(
                    {
                        "code": "ambiguous_fallback_match",
                        "agentId": expected_agent_id,
                        "persona": persona,
                        "matches": sorted(matches),
                    }
                )
                continue
            match = matches[0]
            consumed.add(match)
            actual_agent_id = match
            entry = status_by_agent[match]

        payload, error = _parse_completed(entry)
        if error:
            if isinstance(entry, dict) and "completed" not in entry:
                missing_agent_ids.append(actual_agent_id)
                missing_personas.append(persona)
            else:
                errors.append(
                    {
                        "code": "invalid_completed_payload",
                        "agentId": actual_agent_id,
                        "persona": persona,
                        "message": error,
                    }
                )
            continue

        result_entry: dict[str, Any] = {
            "persona": persona,
            "agentId": actual_agent_id,
            "result": payload,
        }
        descriptor = spec.get("agentDescriptor")
        if isinstance(descriptor, dict):
            result_entry["agentDescriptor"] = descriptor
        results.append(result_entry)

    complete = not missing_agent_ids and not errors
    return {
        "ok": complete and not timed_out,
        "complete": complete,
        "timedOut": timed_out,
        "requiredAgentIds": [_agent_id(spec) for spec in spawn_order],
        "receivedAgentIds": sorted(status_by_agent),
        "missingAgentIds": missing_agent_ids,
        "missingPersonas": missing_personas,
        "results": results,
        "errors": errors,
    }
