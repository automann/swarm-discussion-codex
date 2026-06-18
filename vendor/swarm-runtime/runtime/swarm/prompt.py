"""Prompt-build runtime primitive."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ALLOWED_PHASES = {
    "declaration",
    "argumentation",
    "response",
    "moderator-opening",
    "contrarian",
    "cross-domain",
    "quality-gate",
}
FIXED_ROLE_PHASES = {"moderator-opening", "contrarian", "cross-domain", "quality-gate"}
PINNED_SENDERS = {"moderator", "contrarian", "cross-domain", "historian", "quality-gate"}
ARGUMENTATION_TYPES = {"position_declaration", "moderator_opening"}
PINNED_MESSAGE_TYPES = {"moderator_opening", "stress_test", "cross_domain", "quality_gate", "historian_note"}


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_context_summary(request: dict[str, Any], base_dir: Path | None, errors: list[dict[str, Any]]) -> str:
    inline = request.get("contextSummary")
    if isinstance(inline, str) and inline.strip():
        return inline.strip()

    path_value = request.get("contextSummaryPath")
    if isinstance(path_value, str) and path_value.strip():
        path = Path(path_value)
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        try:
            text = path.read_text()
        except FileNotFoundError:
            errors.append(_issue("missing_context_summary", "contextSummaryPath", f"missing context summary: {path}"))
            return ""
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(
                _issue("unreadable_context_summary", "contextSummaryPath", f"cannot read context summary: {exc}")
            )
            return ""
        if not text.strip():
            errors.append(_issue("empty_context_summary", "contextSummaryPath", "context summary is empty"))
            return ""
        return text.strip()

    errors.append(
        _issue(
            "missing_context_summary",
            "contextSummary",
            "request must include contextSummary or contextSummaryPath",
        )
    )
    return ""


def _persona_label(persona: dict[str, Any]) -> str:
    return str(persona.get("name") or persona.get("id") or "Expert")


def _persona_id(persona: dict[str, Any]) -> str:
    return str(persona.get("id") or persona.get("name") or "expert")


def _list_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, str):
        return value
    return ""


def _profile_block(persona: dict[str, Any]) -> str:
    name = _persona_label(persona)
    persona_id = _persona_id(persona)
    return "\n".join(
        [
            f'You are "{name}" ({persona_id}).',
            f"- Expertise: {_list_text(persona.get('expertise')) or 'not specified'}",
            f"- Thinking style: {persona.get('thinkingStyle') or 'not specified'}",
            f"- Natural bias: {persona.get('bias') or 'not specified'}",
            f"- Reply tendency: {persona.get('replyTendency') or 'not specified'}",
            f"- Stakes: {persona.get('stakes') or 'not specified'}",
            f"- Blind spots: {_list_text(persona.get('blindSpots')) or 'not specified'}",
        ]
    )


def _body_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, dict):
        for key in ("summary", "position", "claim", "text"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(content, sort_keys=True, ensure_ascii=False)
    if isinstance(content, str):
        return content.strip()
    return ""


def _render_full(message: dict[str, Any]) -> str:
    return (
        f"[{message.get('id')}] from {message.get('from')} "
        f"({message.get('type', 'message')}): {_body_text(message)}"
    )


def _render_gist(message: dict[str, Any], max_chars: int = 120) -> str:
    prefix = f"[{message.get('id')}] from {message.get('from')} ({message.get('type', 'message')}): "
    suffix = " (elided)"
    body_budget = max(0, max_chars - len(prefix) - len(suffix))
    body = _body_text(message)
    if len(prefix + body) <= max_chars:
        return prefix + body
    return prefix + body[:body_budget].rstrip() + suffix


def _is_pinned_message(message: dict[str, Any]) -> bool:
    return (
        message.get("role") == "fixed"
        or message.get("type") in PINNED_MESSAGE_TYPES
        or (message.get("from") in PINNED_SENDERS and message.get("type") not in {"argument", "response"})
    )


def _validate_messages(raw_messages: Any, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if raw_messages in (None, ""):
        return []
    if not isinstance(raw_messages, list):
        errors.append(_issue("invalid_messages", "messages", "messages must be a list"))
        return []

    messages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, message in enumerate(raw_messages):
        path = f"messages[{index}]"
        if not isinstance(message, dict):
            errors.append(_issue("invalid_message", path, "message must be an object"))
            continue
        message_id = message.get("id")
        sender = message.get("from")
        if not isinstance(message_id, str) or not message_id.strip():
            errors.append(_issue("invalid_message_id", f"{path}.id", "message id must be a non-empty string"))
            continue
        if message_id in seen:
            errors.append(_issue("duplicate_message_id", f"{path}.id", "message ids must be unique", message_id))
            continue
        if not isinstance(sender, str) or not sender.strip():
            errors.append(_issue("invalid_sender", f"{path}.from", "message sender must be a non-empty string"))
            continue
        seen.add(message_id)
        messages.append(message)
    return messages


def _response_visibility(messages: list[dict[str, Any]], persona_id: str, budget: int) -> dict[str, str]:
    peer_indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("from") != persona_id and not _is_pinned_message(message)
    ]
    remaining = budget
    full_peer_ids: set[str] = set()
    for index in reversed(peer_indexes):
        full_text = _render_full(messages[index])
        if len(full_text) <= remaining:
            full_peer_ids.add(str(messages[index]["id"]))
            remaining -= len(full_text)

    visibility: dict[str, str] = {}
    for message in messages:
        message_id = str(message["id"])
        sender = message.get("from")
        if sender == persona_id or _is_pinned_message(message) or message_id in full_peer_ids:
            visibility[message_id] = "full"
        else:
            visibility[message_id] = "gist"
    return visibility


def _render_with_visibility(messages: list[dict[str, Any]], visibility: dict[str, str]) -> str:
    return "\n".join(
        _render_full(message)
        if visibility.get(str(message["id"])) == "full"
        else _render_gist(message)
        for message in messages
    )


def _output_contract(phase: str) -> dict[str, Any]:
    if phase == "declaration":
        return {
            "format": "json",
            "requiredKeys": ["position", "confidence", "conditions", "wouldChangeIf", "keyRisk"],
            "requiresReferences": False,
        }
    if phase == "response":
        return {
            "format": "json",
            "requiredKeys": [
                "position",
                "reasoning",
                "references",
                "positionShift",
                "currentPosition",
                "previousPosition",
                "shiftReason",
                "shiftTriggerIds",
            ],
            "requiresReferences": True,
            "requiresShiftTriggerIds": True,
        }
    if phase in FIXED_ROLE_PHASES:
        return {"format": "json", "requiresReferences": True, "role": phase}
    return {
        "format": "json",
        "requiredKeys": ["position", "reasoning", "proposals", "references", "counterpoints", "questions"],
        "requiresReferences": True,
    }


def _fixed_role_intro(phase: str) -> str:
    return {
        "moderator-opening": "You are the Moderator. Frame this round around real fault lines, not generic angles.",
        "contrarian": "You are the Contrarian. Target the strongest consensus, not the weakest argument.",
        "cross-domain": "You are the Cross-Domain Thinker. Find the underlying pattern and map a specific analogy.",
        "quality-gate": "You are the Moderator running the quality gate. Score the discussion and name unresolved axes.",
    }[phase]


def _build_prompt_text(
    phase: str,
    request: dict[str, Any],
    context_summary: str,
    messages: list[dict[str, Any]],
    visibility: dict[str, str],
) -> str:
    topic = str(request.get("topic")).strip()
    instruction = str(request.get("instruction") or "").strip()
    persona = request.get("persona") if isinstance(request.get("persona"), dict) else {}

    if phase == "declaration":
        return "\n\n".join(
            [
                _profile_block(persona),
                f"Topic: {topic}",
                "Parent context summary:",
                context_summary,
                "Declare your preliminary position before seeing anyone else's claims.",
                "Output JSON with: position, confidence, conditions, wouldChangeIf, keyRisk.",
            ]
        )

    if phase == "argumentation":
        visible_messages = [
            message for message in messages if message.get("type") in ARGUMENTATION_TYPES
        ]
        discussion = "\n".join(_render_full(message) for message in visible_messages) or "(none)"
        task = instruction or "Make the strongest case for your position while citing visible IDs."
        return "\n\n".join(
            [
                _profile_block(persona),
                f"Current phase: argumentation\nTopic: {topic}",
                "Parent context summary:",
                context_summary,
                "Visible position declarations and moderator framing:",
                discussion,
                f"Task: {task}",
                "Output JSON with: position, reasoning, proposals, references, counterpoints, questions.",
            ]
        )

    if phase == "response":
        slice_text = _render_with_visibility(messages, visibility)
        task = instruction or "Respond to visible arguments and record any position shift triggers."
        return "\n\n".join(
            [
                _profile_block(persona),
                f"Current phase: response\nTopic: {topic}",
                "Parent context summary:",
                context_summary,
                "Discussion so far (cite these IDs):",
                slice_text or "(none)",
                f"Task: {task}",
                "Output JSON with: position, reasoning, proposals, references, counterpoints, questions, positionShift, currentPosition, previousPosition, shiftReason, shiftTriggerIds.",
                "shiftTriggerIds must name the actual full-visible message IDs that changed your position.",
            ]
        )

    discussion = "\n".join(_render_full(message) for message in messages) or "(none)"
    return "\n\n".join(
        [
            _fixed_role_intro(phase),
            f"Topic: {topic}",
            "Parent context summary:",
            context_summary,
            "Discussion so far:",
            discussion,
            "Reference messages by ID. Output structured JSON for the runtime.",
        ]
    )


def build_prompt(request: Any, base_dir: Path | None = None) -> dict[str, Any]:
    """Build a deterministic prompt artifact from a prompt-build request."""

    if not isinstance(request, dict):
        return {
            "ok": False,
            "errors": [_issue("invalid_request", "request", "request must be a JSON object")],
            "warnings": [],
        }

    errors: list[dict[str, Any]] = []
    phase = request.get("phase")
    if not isinstance(phase, str) or phase not in ALLOWED_PHASES:
        errors.append(_issue("invalid_phase", "phase", "phase is not supported", phase))
        phase = ""

    topic = request.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        errors.append(_issue("missing_topic", "topic", "topic must be a non-empty string"))

    context_summary = _load_context_summary(request, base_dir, errors)
    messages = _validate_messages(request.get("messages", []), errors)

    persona = request.get("persona")
    if phase in {"declaration", "argumentation", "response"}:
        if not isinstance(persona, dict):
            errors.append(_issue("missing_persona", "persona", "dynamic phases require a persona object"))
            persona = {}
        elif not persona.get("id"):
            errors.append(_issue("missing_persona_id", "persona.id", "persona.id is required"))

    visibility_budget = request.get("visibilityBudget", 100000)
    if isinstance(visibility_budget, bool) or not isinstance(visibility_budget, int) or visibility_budget < 0:
        errors.append(
            _issue("invalid_visibility_budget", "visibilityBudget", "visibilityBudget must be a non-negative integer")
        )

    if errors:
        return {"ok": False, "errors": errors, "warnings": [], "schemaVersion": SCHEMA_VERSION}

    visibility: dict[str, str] = {}
    if phase == "argumentation":
        visibility = {
            str(message["id"]): "full"
            for message in messages
            if message.get("type") in ARGUMENTATION_TYPES
        }
    elif phase == "response":
        visibility = _response_visibility(messages, _persona_id(persona), visibility_budget)
    elif phase in FIXED_ROLE_PHASES:
        visibility = {str(message["id"]): "full" for message in messages}

    prompt = _build_prompt_text(phase, request, context_summary, messages, visibility)
    injected_ids = list(visibility)
    return {
        "ok": True,
        "errors": [],
        "warnings": [],
        "schemaVersion": SCHEMA_VERSION,
        "phase": phase,
        "roundId": request.get("roundId"),
        "topic": topic.strip(),
        "persona": persona if isinstance(persona, dict) else {"id": phase, "name": phase},
        "prompt": prompt,
        "promptSha256": _sha256(prompt),
        "promptCharCount": len(prompt),
        "contextSummaryCharCount": len(context_summary),
        "visibility": visibility,
        "injectedIds": injected_ids,
        "inputs": {
            "messageCount": len(messages),
            "contextSummarySha256": _sha256(context_summary),
            "visibilityBudget": visibility_budget,
        },
        "outputContract": _output_contract(phase),
    }
