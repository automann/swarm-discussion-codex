"""Discussion-quality signal + stress-policy decision (ADR 0002 / plan 009).

The runtime owns the structural disagreement signal (challenge edges, position
shifts, whether a stress pass ran) and the pre-synthesis ``stress-check`` decision,
so both host adapters enforce ONE quality contract instead of each re-deriving it
(the cross-host drift ADR 0002 exists to prevent).

Structural fields are computed from the round record and are authoritative: if a
coordinator stores a ``quality`` block, validation recomputes them and rejects a
mismatch (``quality_signal_mismatch``). The produced fields (``genuineDisagreement``,
``minorityReportPresent``) are coordinator-supplied and only range/type-checked.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

STRESS_POLICIES = frozenset({"auto", "required", "off"})
_CHALLENGE_RELATIONS = frozenset({"counters", "questions"})
# Phases that exist BEFORE a stress pass; used to re-derive the pre-stress signal
# (so the auto decision cannot be back-dated once stress/response messages land).
_ARGUMENT_PHASE_TYPES = frozenset({"position_declaration", "opening", "argument", "analogy"})


def _issue(code: str, path: str, message: str, value: Any = None) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "path": path, "message": message}
    if value is not None:
        issue["value"] = value
    return issue


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def disagreement_signal(round_record: dict[str, Any], *, pre_stress: bool = False) -> dict[str, Any]:
    """Structural disagreement signal for a round (runtime-authoritative).

    ``pre_stress=True`` counts only challenge edges between argument-phase messages,
    so certification can re-derive what the signal was *before* a stress pass ran.
    """
    if not isinstance(round_record, dict):
        round_record = {}
    messages = _as_list(round_record.get("messages"))
    graph = _as_list(round_record.get("argumentGraph"))
    shifts = _as_list(round_record.get("positionShifts"))

    stress_triggered = any(isinstance(m, dict) and m.get("type") == "stress_test" for m in messages)
    if pre_stress:
        arg_ids = {
            m.get("id")
            for m in messages
            if isinstance(m, dict) and m.get("type") in _ARGUMENT_PHASE_TYPES
        }
        counter = sum(
            1
            for e in graph
            if isinstance(e, dict)
            and e.get("relation") in _CHALLENGE_RELATIONS
            and e.get("from") in arg_ids
            and e.get("to") in arg_ids
        )
    else:
        counter = sum(
            1 for e in graph if isinstance(e, dict) and e.get("relation") in _CHALLENGE_RELATIONS
        )
    return {
        "counterEdgeCount": counter,
        "positionShiftCount": len(shifts),
        "stressTriggered": stress_triggered,
    }


def argument_phase_digest(round_record: Any) -> str:
    """Stable hash of the argument-phase message ids + the edges among them.

    The coordinator persists this at stress-check time so the pre-synthesis ``auto``
    decision cannot be back-dated by inserting a challenge edge into the argument graph
    before finalize: ``validate_stress`` recomputes it from the final record and rejects
    a mismatch (``argument_phase_mutated``).
    """
    record = round_record if isinstance(round_record, dict) else {}
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    arg_ids = sorted(
        m.get("id")
        for m in messages
        if isinstance(m, dict) and m.get("type") in _ARGUMENT_PHASE_TYPES and isinstance(m.get("id"), str)
    )
    arg_id_set = set(arg_ids)
    graph = record.get("argumentGraph") if isinstance(record.get("argumentGraph"), list) else []
    edges = sorted(
        [e.get("from"), e.get("to"), e.get("relation")]
        for e in graph
        if isinstance(e, dict) and e.get("from") in arg_id_set and e.get("to") in arg_id_set
    )
    payload = json.dumps({"messages": arg_ids, "edges": edges}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def effective_stress_policy(manifest: Any) -> str:
    """The effective policy for a discussion; absence is ``off`` (legacy/back-compat)."""
    policy = manifest.get("stressPolicy") if isinstance(manifest, dict) else None
    return policy if policy in STRESS_POLICIES else "off"


def stress_required(policy: str, pre_stress_counter_edges: int) -> bool:
    """Whether a stress pass must run, given the policy and the pre-stress signal."""
    if policy == "required":
        return True
    if policy == "auto":
        return pre_stress_counter_edges == 0
    return False  # off


def quality_summary(round_record: Any, manifest: Any) -> dict[str, Any]:
    """The runtime-authoritative quality block surfaced in trace/evidence.

    Structural fields are computed here; coordinator-produced fields pass through
    from any stored round ``quality`` block (validated separately).
    """
    record = round_record if isinstance(round_record, dict) else {}
    signal = disagreement_signal(record)
    stored = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    synthesis = record.get("synthesis") if isinstance(record.get("synthesis"), dict) else {}
    minority = synthesis.get("minorityReport")
    return {
        "stressPolicy": effective_stress_policy(manifest),
        "stressRequired": stored.get("stressRequired"),
        "stressTriggered": signal["stressTriggered"],
        "counterEdgeCount": signal["counterEdgeCount"],
        "positionShiftCount": signal["positionShiftCount"],
        "genuineDisagreement": stored.get("genuineDisagreement"),
        "minorityReportPresent": bool(minority) if minority is not None else stored.get("minorityReportPresent"),
    }


def build_round_quality(round_record: Any, manifest: Any) -> dict[str, Any]:
    """The runtime-authoritative quality block to PERSIST on a finalized round.

    Structural fields AND ``stressRequired`` are computed by the runtime (overwriting
    any caller-supplied values); the produced fields (``genuineDisagreement``,
    ``minorityReportPresent``) pass through. This is what finalize-round writes, so the
    quality contract is committed, tamper-evident state rather than a transient rebuild.
    """
    record = round_record if isinstance(round_record, dict) else {}
    stored = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    signal = disagreement_signal(record)
    policy = effective_stress_policy(manifest)
    pre_stress = disagreement_signal(record, pre_stress=True)["counterEdgeCount"]
    block: dict[str, Any] = {
        "stressPolicy": policy,
        # stressRequired is the persisted pre-synthesis decision (authoritative); fall
        # back to a finalize-time computation only when the coordinator recorded none.
        "stressRequired": stored["stressRequired"] if isinstance(stored.get("stressRequired"), bool) else stress_required(policy, pre_stress),
        "stressTriggered": signal["stressTriggered"],
        "counterEdgeCount": signal["counterEdgeCount"],
        "positionShiftCount": signal["positionShiftCount"],
    }
    for field in ("genuineDisagreement", "minorityReportPresent", "argumentDigest"):
        if field in stored:
            block[field] = stored[field]
    return block


def validate_quality_block(round_record: Any, effective_policy: str | None = None) -> list[dict[str, Any]]:
    """Recompute the structural signal and reject a stored block that disagrees.

    Inert when the round stores no ``quality`` block. The structural fields are
    runtime-authoritative (anti-forgery, like the descriptor/manifest sha match in
    plan 008); the produced fields are range/type-checked only.
    """
    if not isinstance(round_record, dict) or round_record.get("quality") is None:
        return []
    quality = round_record.get("quality")
    if not isinstance(quality, dict):
        return [_issue("invalid_quality_block", "quality", "quality must be an object", quality)]
    errors: list[dict[str, Any]] = []
    signal = disagreement_signal(round_record)
    for field in ("counterEdgeCount", "positionShiftCount", "stressTriggered"):
        if field in quality and quality[field] != signal[field]:
            errors.append(
                _issue(
                    "quality_signal_mismatch",
                    f"quality.{field}",
                    f"stored {field} disagrees with the runtime-computed signal",
                    {"stored": quality[field], "computed": signal[field]},
                )
            )
    policy = quality.get("stressPolicy")
    if policy is not None and policy not in STRESS_POLICIES:
        errors.append(_issue("invalid_stress_policy", "quality.stressPolicy", "stressPolicy must be one of auto|required|off", policy))
    gd = quality.get("genuineDisagreement")
    if gd is not None and (isinstance(gd, bool) or not isinstance(gd, int) or not 0 <= gd <= 10):
        errors.append(_issue("invalid_quality_block", "quality.genuineDisagreement", "genuineDisagreement must be an integer 0-10", gd))
    for field in ("stressRequired", "minorityReportPresent"):
        if field in quality and not isinstance(quality[field], bool):
            errors.append(_issue("invalid_quality_block", f"quality.{field}", f"{field} must be a boolean", quality[field]))
    # stressRequired is the load-bearing pre-synthesis decision, not a self-report: when
    # the effective policy is known (discussion-level validation has the manifest),
    # recompute it from the policy + pre-stress signal and reject a forged value.
    if effective_policy is not None and isinstance(quality.get("stressRequired"), bool):
        expected = stress_required(effective_policy, disagreement_signal(round_record, pre_stress=True)["counterEdgeCount"])
        if quality["stressRequired"] != expected:
            errors.append(
                _issue(
                    "quality_stress_required_mismatch",
                    "quality.stressRequired",
                    "stored stressRequired disagrees with the runtime decision for the effective policy + pre-stress signal",
                    {"stored": quality["stressRequired"], "expected": expected, "stressPolicy": effective_policy},
                )
            )
    return errors


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _load_current_round(discussion_dir: Path, round_id: int | None) -> tuple[dict[str, Any] | None, int | None, str | None]:
    """Load the in-progress round: prefer a partial (mid-round), else the latest final."""
    rounds_dir = discussion_dir / "rounds"
    if not rounds_dir.exists():
        return None, round_id, None
    if round_id is not None:
        for name, source in ((f"{round_id:03d}.json.partial", "partial"), (f"{round_id:03d}.json", "final")):
            candidate = rounds_dir / name
            if candidate.exists():
                record = _load_json(candidate)
                if isinstance(record, dict):
                    return record, round_id, source
        return None, round_id, None
    for glob, source in (("*.json.partial", "partial"), ("[0-9][0-9][0-9].json", "final")):
        matches = sorted(rounds_dir.glob(glob))
        if matches:
            record = _load_json(matches[-1])
            if isinstance(record, dict):
                rid = record.get("roundId") if isinstance(record.get("roundId"), int) else round_id
                return record, rid, source
    return None, None, None


def stress_check(discussion_dir: Path, round_id: int | None = None) -> dict[str, Any]:
    """Pre-synthesis decision: must a stress pass run for the current round?

    Reads the in-progress round (the latest partial, else the latest final) so the
    signal reflects the argument phase BEFORE synthesis, and the discussion manifest
    for the effective policy. Returns a machine-readable decision the coordinator
    must honor before it finalizes — the trigger is computed once, in the runtime.
    """
    manifest = _load_json(discussion_dir / "manifest.json")
    policy = effective_stress_policy(manifest)
    record, rid, source = _load_current_round(discussion_dir, round_id)
    if record is None:
        return {"ok": False, "errors": [_issue("missing_round", "rounds", "no round state found for stress-check")]}
    counter = disagreement_signal(record, pre_stress=True)["counterEdgeCount"]
    required = stress_required(policy, counter)
    if policy == "off":
        reason = "stressPolicy=off: no stress pass"
    elif policy == "required":
        reason = "stressPolicy=required: stress pass mandatory"
    elif required:
        reason = "stressPolicy=auto: argument round has no counters/questions edges"
    else:
        reason = f"stressPolicy=auto: argument round already has {counter} challenge edge(s)"
    return {
        "ok": True,
        "errors": [],
        "round": rid,
        "roundSource": source,
        "stressPolicy": policy,
        "counterEdgeCount": counter,
        "stressRequired": required,
        "argumentDigest": argument_phase_digest(record),
        "reason": reason,
    }


def _stress_has_response(record: dict[str, Any]) -> bool:
    """True if a ``type=response`` message cites a ``stress_test`` message in its OWN
    ``references``. A bare argumentGraph edge is not enough (review finding 2): graph
    endpoints only have to resolve, so an edge can be synthesized without a real answer.
    """
    messages = record.get("messages") if isinstance(record, dict) else None
    messages = messages if isinstance(messages, list) else []
    stress_ids = {m.get("id") for m in messages if isinstance(m, dict) and m.get("type") == "stress_test"}
    if not stress_ids:
        return False
    for message in messages:
        if isinstance(message, dict) and message.get("type") == "response":
            for ref in message.get("references") or []:
                if isinstance(ref, dict) and ref.get("targetId") in stress_ids:
                    return True
    return False


def validate_stress(discussion_dir: Path, require_stress: bool = False) -> dict[str, Any]:
    """Certification gate for engineered disagreement (``--require-stress``, ADR 0002 D2).

    Inert unless ``require_stress``; then keyed off the declared stressPolicy:
      - any policy, when a stress pass ran: a response must reference the stress message
        (``stress_response_missing``);
      - ``required``: every round must run a stress pass (``stress_required_not_triggered``);
      - ``auto``: a round whose argument phase had no challenge edges must run a stress pass
        (``auto_stress_skipped``);
      - ``off`` (or absent): no debate-depth assertion.
    """
    errors: list[dict[str, Any]] = []
    manifest = _load_json(discussion_dir / "manifest.json")
    policy = effective_stress_policy(manifest)
    rounds_dir = discussion_dir / "rounds"
    round_files = sorted(rounds_dir.glob("[0-9][0-9][0-9].json")) if rounds_dir.exists() else []
    if require_stress and policy != "off":
        for round_file in round_files:
            record = _load_json(round_file)
            if not isinstance(record, dict):
                continue
            where = str(round_file)
            triggered = disagreement_signal(record)["stressTriggered"]
            if triggered and not _stress_has_response(record):
                errors.append(_issue("stress_response_missing", where, "a stress pass ran but no response references the stress_test message"))
            if policy == "required" and not triggered:
                errors.append(_issue("stress_required_not_triggered", where, "stressPolicy=required but this round ran no stress pass"))
            if policy == "auto":
                # auto is data-driven, so the authority is the PERSISTED pre-synthesis
                # decision, not a re-derivation from the (mutable) final record: require
                # it, reject argument-graph back-dating via the digest, and honor it.
                quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
                persisted_required = quality.get("stressRequired")
                persisted_digest = quality.get("argumentDigest")
                if not isinstance(persisted_required, bool) or not isinstance(persisted_digest, str):
                    errors.append(_issue("stress_decision_unrecorded", where, "stressPolicy=auto requires a persisted pre-synthesis decision (quality.stressRequired + quality.argumentDigest from stress-check)"))
                else:
                    if persisted_digest != argument_phase_digest(record):
                        errors.append(_issue("argument_phase_mutated", where, "argument phase changed after the pre-synthesis stress-check decision (argumentDigest mismatch): the auto decision was back-dated"))
                    if persisted_required and not triggered:
                        errors.append(_issue("auto_stress_skipped", where, "stressPolicy=auto: the pre-synthesis decision required a stress pass but none ran"))
    return {"ok": not errors, "errors": errors, "summary": {"stressPolicy": policy, "rounds": len(round_files)}}
