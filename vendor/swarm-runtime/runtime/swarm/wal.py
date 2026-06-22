"""Write-ahead-log helpers for round state."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from swarm._shared import MESSAGE_ID, fsync_dir as _fsync_dir
from swarm.quality import build_round_quality
from swarm.validation import ALLOWED_RELATIONS, validate_round_record


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _round_paths(discussion_dir: Path, round_id: int) -> dict[str, Path]:
    rounds_dir = discussion_dir / "rounds"
    stem = f"{round_id:03d}"
    return {
        "rounds": rounds_dir,
        "partial": rounds_dir / f"{stem}.json.partial",
        "final": rounds_dir / f"{stem}.json",
        "tmp": rounds_dir / f"{stem}.json.tmp",
        "progress": discussion_dir / "progress.md",
        "events": discussion_dir / "events.jsonl",
    }


def _read_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        return None, _issue("unreadable_state", str(path), f"cannot read state file: {exc}")
    except json.JSONDecodeError as exc:
        return None, _issue("invalid_json", str(path), f"invalid JSON in state file: {exc}")
    if not isinstance(payload, dict):
        return None, _issue("invalid_state", str(path), "state file must contain a JSON object")
    return payload, None


def _event_seq(events_path: Path) -> int:
    if not events_path.exists():
        return 1
    return sum(1 for line in events_path.read_text().splitlines() if line.strip()) + 1


def append_event(discussion_dir: Path, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    discussion_dir.mkdir(parents=True, exist_ok=True)
    events_path = discussion_dir / "events.jsonl"
    events_existed = events_path.exists()
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seq": _event_seq(events_path),
        "type": event_type,
        "data": data,
    }
    with events_path.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if not events_existed:
        _fsync_dir(discussion_dir)
    return event


def _load_state(
    discussion_dir: Path, round_id: int
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    paths = _round_paths(discussion_dir, round_id)
    if paths["partial"].exists():
        state, issue = _read_json(paths["partial"])
        return state, "partial", issue
    if paths["final"].exists():
        state, issue = _read_json(paths["final"])
        return state, "final", issue
    return None, None, None


def _empty_state(round_id: int, phase: str) -> dict[str, Any]:
    return {
        "roundId": round_id,
        "round": round_id,
        "phase": phase,
        "messages": [],
        "argumentGraph": [],
        "positionShifts": [],
        "personaContextLog": {},
    }


def _seqs_from_state(state: dict[str, Any], round_id: int) -> set[int]:
    seqs: set[int] = set()
    for message in state.get("messages") or []:
        if not isinstance(message, dict):
            continue
        match = MESSAGE_ID.match(str(message.get("id") or ""))
        if match and int(match.group(1)) == round_id:
            seqs.add(int(match.group(2)))
    return seqs


def _seqs_on_disk(discussion_dir: Path, round_id: int) -> tuple[set[int], list[dict[str, Any]]]:
    paths = _round_paths(discussion_dir, round_id)
    seqs: set[int] = set()
    issues: list[dict[str, Any]] = []
    for path in (paths["partial"], paths["final"]):
        if path.exists():
            state, issue = _read_json(path)
            if issue is not None:
                issues.append(issue)
                continue
            seqs.update(_seqs_from_state(state, round_id))
    return seqs, issues


def max_seq(discussion_dir: Path, round_id: int) -> tuple[int, list[dict[str, Any]]]:
    seqs, issues = _seqs_on_disk(discussion_dir, round_id)
    return (max(seqs) if seqs else 0), issues


def next_message_id(discussion_dir: Path, round_id: int) -> tuple[str, list[dict[str, Any]]]:
    seq, issues = max_seq(discussion_dir, round_id)
    return f"r{round_id}-msg-{seq + 1:03d}", issues


def _max_message_id(discussion_dir: Path, round_id: int) -> str | None:
    seq, _ = max_seq(discussion_dir, round_id)
    return f"r{round_id}-msg-{seq:03d}" if seq else None


def _validate_message_payload(
    state: dict[str, Any], message: dict[str, Any], round_id: int
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if "id" in message:
        errors.append(_issue("message_id_must_be_minted", "message.id", "append-message mints message ids"))
    sender = message.get("from")
    if not isinstance(sender, str) or not sender.strip():
        errors.append(_issue("invalid_sender", "message.from", "message sender must be a non-empty string"))
    kind = message.get("type")
    if not isinstance(kind, str) or not kind.strip():
        errors.append(_issue("invalid_message_type", "message.type", "message type must be a non-empty string"))
    if "content" not in message:
        errors.append(_issue("missing_content", "message.content", "message content is required"))

    present = {
        item.get("id")
        for item in state.get("messages", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    references = message.get("references", [])
    if references is None:
        references = []
    if not isinstance(references, list):
        errors.append(_issue("invalid_references", "message.references", "references must be a list"))
        return errors
    for index, ref in enumerate(references):
        path = f"message.references[{index}]"
        if not isinstance(ref, dict):
            errors.append(_issue("invalid_reference", path, "reference must be an object"))
            continue
        relation = ref.get("relation")
        if relation not in ALLOWED_RELATIONS:
            errors.append(
                _issue(
                    "invalid_relation",
                    f"{path}.relation",
                    "relation must be one of counters, extends, questions, supports",
                    relation,
                )
            )
        target_id = ref.get("targetId")
        if target_id not in present:
            errors.append(
                _issue(
                    "unresolved_reference",
                    f"{path}.targetId",
                    "reference target is not in WAL state",
                    target_id,
                )
            )
        match = MESSAGE_ID.match(str(target_id or ""))
        if match and int(match.group(1)) != round_id:
            errors.append(
                _issue(
                    "cross_round_reference",
                    f"{path}.targetId",
                    "append-message references must stay in round",
                    target_id,
                )
            )
    return errors


def _round_guard(
    discussion_dir: Path, round_id: int, state: dict[str, Any], allow_final: bool = False
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if isinstance(round_id, bool) or not isinstance(round_id, int) or round_id < 1:
        errors.append(_issue("invalid_round_id", "round", "round must be a positive integer", round_id))
        return errors
    if not isinstance(state, dict):
        errors.append(_issue("invalid_state", "state", "state must be a JSON object"))
        return errors
    declared = state.get("roundId", round_id)
    if isinstance(declared, bool) or not isinstance(declared, int) or declared != round_id:
        errors.append(
            _issue("round_id_mismatch", "state.roundId", "state roundId must match the target round", declared)
        )
    paths = _round_paths(discussion_dir, round_id)
    if not allow_final and paths["final"].exists():
        errors.append(_issue("round_finalized", "round", "cannot write to a finalized round", round_id))
    if round_id > 1:
        previous = _round_paths(discussion_dir, round_id - 1)
        if not previous["final"].exists():
            errors.append(
                _issue(
                    "round_not_sequential",
                    "round",
                    f"round {round_id} requires round {round_id - 1} to be finalized first",
                    round_id,
                )
            )
    return errors


def checkpoint(discussion_dir: Path, round_id: int, phase: str, state: dict[str, Any]) -> dict[str, Any]:
    guard_errors = _round_guard(discussion_dir, round_id, state)
    if guard_errors:
        return {"ok": False, "errors": guard_errors}

    paths = _round_paths(discussion_dir, round_id)
    payload = dict(state)
    payload["roundId"] = round_id
    payload["round"] = round_id
    payload["phase"] = phase
    paths["rounds"].mkdir(parents=True, exist_ok=True)

    with paths["tmp"].open("w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(paths["tmp"], paths["partial"])
    _fsync_dir(paths["rounds"])

    message_ids = [
        message.get("id")
        for message in payload.get("messages", [])
        if isinstance(message, dict) and isinstance(message.get("id"), str)
    ]
    if message_ids:
        progress_seen: set[str] = set()
        progress_existed = paths["progress"].exists()
        if progress_existed:
            for line in paths["progress"].read_text().splitlines():
                token = line.split(" ", 1)[0].strip()
                if token:
                    progress_seen.add(token)
        with paths["progress"].open("a") as progress:
            for message_id in message_ids:
                if message_id not in progress_seen:
                    progress.write(f"{message_id} emitted\n")
            progress.flush()
            os.fsync(progress.fileno())
        if not progress_existed:
            _fsync_dir(discussion_dir)

    event = append_event(
        discussion_dir,
        "checkpoint_written",
        {
            "round": round_id,
            "phase": phase,
            "messageCount": len(payload.get("messages", []) or []),
            "path": str(paths["partial"]),
        },
    )
    return {
        "ok": True,
        "errors": [],
        "round": round_id,
        "phase": phase,
        "path": str(paths["partial"]),
        "event": event,
    }


def append_message(
    discussion_dir: Path, round_id: int, phase: str, message: dict[str, Any]
) -> dict[str, Any]:
    state, source, state_issue = _load_state(discussion_dir, round_id)
    if state_issue is not None:
        return {"ok": False, "errors": [state_issue]}
    if source == "final":
        return {
            "ok": False,
            "errors": [_issue("round_finalized", "round", "cannot append to a finalized round", round_id)],
        }
    if state is None:
        state = _empty_state(round_id, phase)
    if not isinstance(message, dict):
        return {
            "ok": False,
            "errors": [_issue("invalid_message", "message", "message must be a JSON object")],
        }

    errors = _validate_message_payload(state, message, round_id)
    if errors:
        return {"ok": False, "errors": errors}

    minted_id, mint_issues = next_message_id(discussion_dir, round_id)
    if mint_issues:
        return {"ok": False, "errors": mint_issues}
    new_message = dict(message)
    new_message["id"] = minted_id
    new_message.setdefault("references", [])
    state.setdefault("messages", []).append(new_message)
    graph = state.setdefault("argumentGraph", [])
    for ref in new_message.get("references", []):
        graph.append({"from": minted_id, "to": ref["targetId"], "relation": ref["relation"]})

    checkpoint_result = checkpoint(discussion_dir, round_id, phase, state)
    event = append_event(
        discussion_dir,
        "message_appended",
        {"round": round_id, "phase": phase, "messageId": minted_id, "from": new_message.get("from")},
    )
    return {
        "ok": True,
        "errors": [],
        "message": new_message,
        "checkpoint": checkpoint_result,
        "event": event,
    }


_STRESS_POLICIES = frozenset({"auto", "required", "off"})
_MODE_DEFAULT_STRESS = {"lightweight": "off", "standard": "auto", "deep": "required"}


def _default_stress_policy(mode: str) -> str:
    """Default stressPolicy for a mode tier; non-tier modes get 'off' (back-compat)."""
    return _MODE_DEFAULT_STRESS.get(mode, "off")


def init_discussion(
    discussion_dir: Path,
    discussion_id: str,
    mode: str = "standard",
    title: str | None = None,
    stress_policy: str | None = None,
) -> dict[str, Any]:
    """Scaffold a discussion directory and its manifest. Fail loud if it exists."""
    if not isinstance(discussion_id, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*\Z", discussion_id):
        return {
            "ok": False,
            "errors": [
                _issue("invalid_discussion_id", "discussionId", "must match ^[A-Za-z0-9][A-Za-z0-9_-]*$", discussion_id)
            ],
        }
    if isinstance(stress_policy, str) and stress_policy.strip() and stress_policy not in _STRESS_POLICIES:
        return {
            "ok": False,
            "errors": [_issue("invalid_stress_policy", "stressPolicy", "must be one of auto|required|off", stress_policy)],
        }
    manifest_path = discussion_dir / "manifest.json"
    if manifest_path.exists():
        return {
            "ok": False,
            "errors": [_issue("already_initialized", str(manifest_path), "discussion already initialized")],
        }
    for sub in ("context", "rounds", "artifacts"):
        (discussion_dir / sub).mkdir(parents=True, exist_ok=True)
    resolved_mode = mode if isinstance(mode, str) and mode.strip() else "standard"
    resolved_stress_policy = (
        stress_policy
        if isinstance(stress_policy, str) and stress_policy in _STRESS_POLICIES
        else _default_stress_policy(resolved_mode)
    )
    manifest = {
        "schemaVersion": 1,
        "id": discussion_id,
        "mode": resolved_mode,
        "stressPolicy": resolved_stress_policy,
        "status": "active",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if isinstance(title, str) and title.strip():
        manifest["title"] = title
    tmp_path = manifest_path.with_name(f".manifest.json.{os.getpid()}.tmp")
    with tmp_path.open("w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, manifest_path)
    _fsync_dir(discussion_dir)
    event = append_event(
        discussion_dir,
        "discussion_initialized",
        {"discussionId": discussion_id, "mode": resolved_mode, "stressPolicy": resolved_stress_policy},
    )
    return {
        "ok": True,
        "errors": [],
        "manifestPath": str(manifest_path),
        "discussionId": discussion_id,
        "mode": resolved_mode,
        "stressPolicy": resolved_stress_policy,
        "nextHelperCommand": "swarm-rt context-build --brief <brief.json> --out context/summary.md",
        "event": event,
    }


def _derive_round_metadata(final_state: dict[str, Any]) -> dict[str, Any]:
    """Fill metadata/timestamp from messages when the caller omitted them.

    Never overwrites caller-supplied values: if metadata or timestamp is
    present it passes through unchanged so the validator still catches
    inconsistent input (no silent repair).
    """
    if not isinstance(final_state, dict):
        return final_state
    derived = dict(final_state)
    messages = derived.get("messages") or []
    graph = derived.get("argumentGraph") or []
    if isinstance(messages, list) and "metadata" not in derived:
        derived["metadata"] = {
            "messageCount": len(messages),
            "referenceCount": len(graph) if isinstance(graph, list) else 0,
            "participants": sorted(
                {
                    message.get("from")
                    for message in messages
                    if isinstance(message, dict) and isinstance(message.get("from"), str)
                }
            ),
        }
    derived.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return derived


def _load_manifest(discussion_dir: Path) -> dict[str, Any] | None:
    try:
        manifest = json.loads((discussion_dir / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def finalize_round(discussion_dir: Path, round_id: int, final_state: dict[str, Any]) -> dict[str, Any]:
    guard_errors = _round_guard(discussion_dir, round_id, final_state)
    if guard_errors:
        return {"ok": False, "errors": guard_errors}

    final_state = _derive_round_metadata(final_state)
    # Persist the runtime-owned quality block on the round (plan 009 step 3): the
    # structural fields + stressRequired are authoritative, so the quality contract is
    # committed, tamper-evident state rather than a transient trace/evidence rebuild.
    final_state["quality"] = build_round_quality(final_state, _load_manifest(discussion_dir))
    validation = validate_round_record(final_state)
    if not validation["ok"]:
        return {"ok": False, "errors": validation["errors"], "warnings": validation["warnings"]}

    checkpoint_result = checkpoint(discussion_dir, round_id, "complete", final_state)
    if not checkpoint_result.get("ok"):
        return {"ok": False, "errors": checkpoint_result.get("errors", [])}
    paths = _round_paths(discussion_dir, round_id)
    if not paths["partial"].exists():
        return {
            "ok": False,
            "errors": [_issue("missing_partial", str(paths["partial"]), "final checkpoint did not produce partial")],
        }
    os.replace(paths["partial"], paths["final"])
    _fsync_dir(paths["rounds"])
    event = append_event(
        discussion_dir,
        "round_finalized",
        {
            "round": round_id,
            "messageCount": len(final_state.get("messages", []) or []),
            "path": str(paths["final"]),
        },
    )
    return {
        "ok": True,
        "errors": [],
        "warnings": validation["warnings"],
        "round": round_id,
        "path": str(paths["final"]),
        "checkpoint": checkpoint_result,
        "event": event,
    }


def _highest_round(paths: list[Path], suffix: str) -> int | None:
    rounds = []
    for path in paths:
        name = path.name.removesuffix(suffix)
        if name.isdigit():
            rounds.append(int(name))
    return max(rounds) if rounds else None


def resume_plan(discussion_dir: Path) -> dict[str, Any]:
    rounds_dir = discussion_dir / "rounds"
    if not rounds_dir.exists():
        return {"ok": True, "source": "none", "nextAction": "start_round", "round": None}

    partial_round = _highest_round(list(rounds_dir.glob("*.json.partial")), ".json.partial")
    final_round = _highest_round(list(rounds_dir.glob("*.json")), ".json")
    candidates = [item for item in (partial_round, final_round) if item is not None]
    if not candidates:
        return {"ok": True, "source": "none", "nextAction": "start_round", "round": None}

    top = max(candidates)
    paths = _round_paths(discussion_dir, top)
    if paths["partial"].exists():
        state, issue = _read_json(paths["partial"])
        source = "partial"
        action = "resume_round"
        state_path = paths["partial"]
    else:
        state, issue = _read_json(paths["final"])
        source = "final"
        action = "start_next_round"
        state_path = paths["final"]

    if issue is not None:
        return {
            "ok": False,
            "errors": [issue],
            "source": source,
            "round": top,
            "statePath": str(state_path),
            "nextAction": "inspect_artifacts",
        }

    next_id, seq_issues = next_message_id(discussion_dir, top)
    if seq_issues:
        return {
            "ok": False,
            "errors": seq_issues,
            "source": source,
            "round": top,
            "statePath": str(state_path),
            "nextAction": "inspect_artifacts",
        }

    return {
        "ok": True,
        "source": source,
        "round": top,
        "phase": state.get("phase") if source == "partial" else "complete",
        "maxId": _max_message_id(discussion_dir, top),
        "nextMessageId": next_id,
        "statePath": str(state_path),
        "messageCount": len(state.get("messages", []) or []),
        "nextAction": action,
    }
