"""Runtime validation helpers for discussion artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm._shared import MESSAGE_ID

ALLOWED_RELATIONS = {"supports", "counters", "extends", "questions"}
COMPLETED_STATUSES = {"completed", "complete", "done"}


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _resolves(value: Any, present: set[str]) -> bool:
    return isinstance(value, str) and value in present


def _shift_trigger_ids(shift: dict[str, Any]) -> list[Any]:
    trigger = shift.get("trigger")
    if isinstance(trigger, list):
        return trigger
    if trigger is None:
        return []
    return [trigger]


def _require_list(
    round_record: dict[str, Any], field: str, code: str, errors: list[dict[str, Any]]
) -> list[Any]:
    value = round_record.get(field)
    if isinstance(value, list):
        return value
    if field in round_record:
        errors.append(_issue(code, field, f"{field} must be a list", value))
    return []


def _load_json(path: Path, errors: list[dict[str, Any]], label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        errors.append(_issue("missing_file", label, f"missing file: {path}"))
    except json.JSONDecodeError as exc:
        errors.append(_issue("invalid_json", label, f"invalid JSON: {exc}"))
    return None


def validate_round_record(round_record: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    required = (
        "roundId",
        "topic",
        "mode",
        "timestamp",
        "messages",
        "argumentGraph",
        "positionShifts",
        "synthesis",
        "metadata",
    )
    for field in required:
        if field not in round_record:
            errors.append(_issue("missing_field", field, f"missing field: {field}"))

    round_id = round_record.get("roundId")
    if not isinstance(round_id, int):
        errors.append(_issue("invalid_round_id", "roundId", "roundId must be an integer", round_id))

    messages = _require_list(round_record, "messages", "invalid_messages", errors)

    message_ids: list[str] = []
    seqs: list[int] = []
    for index, message in enumerate(messages):
        path = f"messages[{index}]"
        if not isinstance(message, dict):
            errors.append(_issue("invalid_message", path, "message must be an object"))
            continue

        message_id = message.get("id")
        if not isinstance(message_id, str):
            errors.append(_issue("invalid_message_id", f"{path}.id", "message id must be a string", message_id))
            continue

        message_ids.append(message_id)
        match = MESSAGE_ID.match(message_id)
        if not match:
            errors.append(_issue("invalid_message_id", f"{path}.id", "message id violates rN-msg-NNN grammar", message_id))
            continue

        if isinstance(round_id, int) and int(match.group(1)) != round_id:
            errors.append(
                _issue(
                    "message_round_mismatch",
                    f"{path}.id",
                    "message id round does not match roundId",
                    message_id,
                )
            )
        seqs.append(int(match.group(2)))

    if len(message_ids) != len(set(message_ids)):
        errors.append(_issue("duplicate_message_id", "messages", "message ids must be unique"))
    expected_seqs = list(range(1, len(messages) + 1))
    if sorted(seqs) != expected_seqs:
        errors.append(
            _issue(
                "message_id_gap",
                "messages",
                f"message ids must be gapless 1..{len(messages)}",
                sorted(seqs),
            )
        )

    present = set(message_ids)
    argument_graph = _require_list(round_record, "argumentGraph", "invalid_argument_graph", errors)

    for index, edge in enumerate(argument_graph):
        path = f"argumentGraph[{index}]"
        if not isinstance(edge, dict):
            errors.append(_issue("invalid_edge", path, "argumentGraph edge must be an object"))
            continue
        relation = edge.get("relation")
        if relation not in ALLOWED_RELATIONS:
            errors.append(
                _issue(
                    "invalid_relation",
                    f"{path}.relation",
                    "relation must be one of counters, extends, questions, supports",
                    relation,
                )
            )
        for key in ("from", "to"):
            if not _resolves(edge.get(key), present):
                errors.append(
                    _issue(
                        "unresolved_edge",
                        f"{path}.{key}",
                        "argumentGraph endpoint must resolve to a present message id",
                        edge.get(key),
                    )
                )

    for message_index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        references = message.get("references")
        path = f"messages[{message_index}].references"
        if references is None and "references" not in message:
            references = []
        if not isinstance(references, list):
            errors.append(_issue("invalid_references", path, "references must be a list", references))
            continue
        for ref_index, ref in enumerate(references):
            ref_path = f"{path}[{ref_index}]"
            if not isinstance(ref, dict):
                errors.append(_issue("invalid_reference", ref_path, "reference must be an object"))
                continue
            relation = ref.get("relation")
            if relation not in ALLOWED_RELATIONS:
                errors.append(
                    _issue(
                        "invalid_relation",
                        f"{ref_path}.relation",
                        "relation must be one of counters, extends, questions, supports",
                        relation,
                    )
                )
            if not _resolves(ref.get("targetId"), present):
                errors.append(
                    _issue(
                        "unresolved_reference",
                        f"{ref_path}.targetId",
                        "reference target must resolve to a present message id",
                        ref.get("targetId"),
                    )
                )

    position_shifts = _require_list(round_record, "positionShifts", "invalid_position_shifts", errors)

    for shift_index, shift in enumerate(position_shifts):
        path = f"positionShifts[{shift_index}]"
        if not isinstance(shift, dict):
            errors.append(_issue("invalid_position_shift", path, "position shift must be an object"))
            continue
        expert = shift.get("expert")
        if not isinstance(expert, str) or not expert.strip():
            errors.append(
                _issue("invalid_shift_expert", f"{path}.expert", "position shift must name its expert", expert)
            )
        trigger_ids = _shift_trigger_ids(shift)
        if not trigger_ids:
            errors.append(
                _issue(
                    "missing_shift_trigger",
                    f"{path}.trigger",
                    "position shift must cite at least one trigger message id",
                )
            )
        for trigger_id in trigger_ids:
            if not _resolves(trigger_id, present):
                errors.append(
                    _issue(
                        "unresolved_shift_trigger",
                        f"{path}.trigger",
                        "position shift trigger must resolve to a present message id",
                        trigger_id,
                    )
                )

    if not round_record.get("synthesis"):
        errors.append(_issue("missing_synthesis", "synthesis", "committed round must include synthesis"))

    metadata = round_record.get("metadata") or {}
    if not isinstance(metadata, dict):
        errors.append(_issue("invalid_metadata", "metadata", "metadata must be an object"))
        metadata = {}

    if metadata.get("messageCount") != len(messages):
        errors.append(
            _issue(
                "metadata_mismatch",
                "metadata.messageCount",
                "metadata.messageCount must equal len(messages)",
                metadata.get("messageCount"),
            )
        )
    if metadata.get("referenceCount") != len(argument_graph):
        errors.append(
            _issue(
                "metadata_mismatch",
                "metadata.referenceCount",
                "metadata.referenceCount must equal len(argumentGraph)",
                metadata.get("referenceCount"),
            )
        )
    participants = metadata.get("participants")
    distinct_senders = {
        message.get("from")
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("from"), str)
    }
    participant_set = (
        {item for item in participants if isinstance(item, str)}
        if isinstance(participants, list) and all(isinstance(item, str) for item in participants)
        else None
    )
    if participant_set is None or participant_set != distinct_senders:
        errors.append(
            _issue(
                "metadata_mismatch",
                "metadata.participants",
                "metadata.participants must equal distinct message senders",
                participants,
            )
        )

    context_log = round_record.get("personaContextLog")
    if context_log is not None and not isinstance(context_log, dict):
        errors.append(
            _issue(
                "invalid_persona_context_log",
                "personaContextLog",
                "personaContextLog must be an object",
                context_log,
            )
        )
        context_log = None
    dict_shifts = [
        (shift_index, shift)
        for shift_index, shift in enumerate(position_shifts)
        if isinstance(shift, dict)
    ]
    if dict_shifts and not context_log:
        errors.append(
            _issue(
                "shift_provenance_unverifiable",
                "personaContextLog",
                "position shifts require personaContextLog entries proving full visibility",
            )
        )
    elif context_log:
        for shift_index, shift in dict_shifts:
            expert = shift.get("expert")
            visibility = context_log.get(expert, {}) if isinstance(expert, str) else {}
            for trigger_id in _shift_trigger_ids(shift):
                if not isinstance(trigger_id, str):
                    continue
                if not isinstance(visibility, dict) or visibility.get(trigger_id) != "full":
                    errors.append(
                        _issue(
                            "shift_trigger_not_visible",
                            f"positionShifts[{shift_index}].trigger",
                            "position shift trigger must have been visible in full",
                            trigger_id,
                        )
                    )
    else:
        warnings.append(
            _issue(
                "missing_persona_context_log",
                "personaContextLog",
                "shift provenance skipped because personaContextLog is absent",
            )
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "roundId": round_id,
            "messageCount": len(messages),
            "argumentEdgeCount": len(argument_graph),
            "relationEnum": sorted(ALLOWED_RELATIONS),
        },
    }


def validate_round_file(path: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    data = _load_json(path, errors, str(path))
    if errors:
        return {"ok": False, "errors": errors, "warnings": [], "summary": {}}
    if not isinstance(data, dict):
        return {
            "ok": False,
            "errors": [_issue("invalid_round", str(path), "round file must contain a JSON object")],
            "warnings": [],
            "summary": {},
        }
    result = validate_round_record(data)
    result["path"] = str(path)
    return result


def validate_discussion_dir(path: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not path.exists():
        return {
            "ok": False,
            "errors": [_issue("missing_directory", str(path), "discussion directory does not exist")],
            "warnings": [],
            "summary": {},
        }
    if not path.is_dir():
        return {
            "ok": False,
            "errors": [_issue("invalid_directory", str(path), "discussion path is not a directory")],
            "warnings": [],
            "summary": {},
        }

    manifest = _load_json(path / "manifest.json", errors, "manifest.json")
    if manifest is not None and not isinstance(manifest, dict):
        errors.append(_issue("invalid_manifest", "manifest.json", "manifest must be a JSON object"))
        manifest = {}

    summary_path = path / "context" / "summary.md"
    if not summary_path.exists():
        errors.append(_issue("missing_summary", "context/summary.md", "context summary is required"))
    elif not summary_path.read_text().strip():
        errors.append(_issue("empty_summary", "context/summary.md", "context summary must be non-empty"))

    rounds_dir = path / "rounds"
    round_files = sorted(rounds_dir.glob("[0-9][0-9][0-9].json")) if rounds_dir.exists() else []
    partial_files = sorted(rounds_dir.glob("*.json.partial")) if rounds_dir.exists() else []
    if not round_files:
        errors.append(_issue("missing_rounds", "rounds", "at least one committed round is required"))

    round_results = []
    for round_file in round_files:
        round_result = validate_round_file(round_file)
        round_results.append(round_result)
        for issue in round_result["errors"]:
            nested = dict(issue)
            nested["path"] = f"{round_file.relative_to(path)}:{issue['path']}"
            errors.append(nested)
        warnings.extend(round_result["warnings"])
        file_round = int(round_file.name.removesuffix(".json"))
        record_round = round_result.get("summary", {}).get("roundId")
        if isinstance(record_round, int) and record_round != file_round:
            errors.append(
                _issue(
                    "round_file_mismatch",
                    str(round_file.relative_to(path)),
                    "round file name does not match the record roundId",
                    record_round,
                )
            )

    status = manifest.get("status") if isinstance(manifest, dict) else None
    if status is not None and not isinstance(status, str):
        errors.append(_issue("invalid_status", "manifest.json:status", "manifest status must be a string", status))
        status = None
    if status in COMPLETED_STATUSES:
        if partial_files:
            errors.append(
                _issue(
                    "stale_partial",
                    "rounds",
                    "completed discussions must not leave partial round files",
                    [str(p.relative_to(path)) for p in partial_files],
                )
            )

        tmp_dir = path / "tmp"
        if tmp_dir.exists() and any(tmp_dir.iterdir()):
            errors.append(_issue("leftover_tmp", "tmp", "completed discussions must not leave tmp files"))

        synthesis = path / "artifacts" / "synthesis.md"
        if not synthesis.exists():
            errors.append(
                _issue("missing_artifact", "artifacts/synthesis.md", "completed discussion requires synthesis.md")
            )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "discussionId": manifest.get("id") if isinstance(manifest, dict) else None,
            "status": status,
            "roundCount": len(round_files),
            "validatedRounds": sum(1 for result in round_results if result["ok"]),
        },
    }
