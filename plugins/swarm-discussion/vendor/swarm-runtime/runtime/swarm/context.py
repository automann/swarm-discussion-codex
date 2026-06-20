"""Context-summary builder for parent-agent briefs."""

from __future__ import annotations

import hashlib
from typing import Any


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _required_text(payload: dict[str, Any], field: str, errors: list[dict[str, Any]]) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(_issue("missing_field", field, f"{field} must be a non-empty string"))
        return ""
    return value.strip()


def _optional_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    return value.strip() if isinstance(value, str) else ""


def _text_list(payload: dict[str, Any], field: str, errors: list[dict[str, Any]]) -> list[str]:
    value = payload.get(field, [])
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(_issue("invalid_list", field, f"{field} must be a list of non-empty strings"))
        return []
    return [item.strip() for item in value]


def _bullet_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"## {title}", "", *[f"- {item}" for item in items], ""]


def build_context_summary(brief: Any) -> dict[str, Any]:
    """Build a deterministic Markdown context summary from a parent brief."""

    if not isinstance(brief, dict):
        return {
            "ok": False,
            "errors": [_issue("invalid_brief", "brief", "brief must be a JSON object")],
            "warnings": [],
            "summaryMarkdown": "",
        }

    errors: list[dict[str, Any]] = []
    topic = _required_text(brief, "topic", errors)
    objective = _required_text(brief, "objective", errors)
    mode = _optional_text(brief, "mode") or "standard"
    discussion_id = _optional_text(brief, "discussionId")
    parent_context = _optional_text(brief, "parentContext")
    constraints = _text_list(brief, "constraints", errors)
    known_facts = _text_list(brief, "knownFacts", errors)
    success_criteria = _text_list(brief, "successCriteria", errors)

    if errors:
        return {"ok": False, "errors": errors, "warnings": [], "summaryMarkdown": ""}

    lines = [
        "# Context Summary",
        "",
        "## Topic",
        "",
        topic,
        "",
        "## Objective",
        "",
        objective,
        "",
        "## Operating Mode",
        "",
        mode,
        "",
    ]
    if discussion_id:
        lines.extend(["## Discussion ID", "", discussion_id, ""])
    if parent_context:
        lines.extend(["## Parent Context", "", parent_context, ""])
    lines.extend(_bullet_section("Constraints", constraints))
    lines.extend(_bullet_section("Known Facts", known_facts))
    lines.extend(_bullet_section("Success Criteria", success_criteria))
    lines.extend(
        [
            "## Alignment Rule",
            "",
            "Keep every contribution anchored to the topic, objective, constraints, known facts, and success criteria above.",
            "",
        ]
    )

    summary_markdown = "\n".join(lines).rstrip() + "\n"
    digest = hashlib.sha256(summary_markdown.encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "errors": [],
        "warnings": [],
        "summaryMarkdown": summary_markdown,
        "summarySha256": digest,
        "summary": {
            "discussionId": discussion_id or None,
            "topic": topic,
            "mode": mode,
            "charCount": len(summary_markdown),
        },
    }
