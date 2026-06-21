#!/usr/bin/env python3
"""Minimal CLI entrypoint for the swarm discussion runtime incubator."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from swarm import __version__, planned_commands
from swarm.adapter import validate_host_transport_metadata
from swarm.audit import build_evidence, build_trace
from swarm.capabilities import (
    capability_doctor_report,
    default_profile_path,
    load_jsonl,
)
from swarm.collect import collect_merge
from swarm.contract import load_runtime_contract, validate_runtime_contract
from swarm.context import build_context_summary
from swarm.loop import validate_minimal_loop
from swarm.prompt import build_prompt
from swarm.smoke import adapter_smoke
from swarm.transport import append_wait_batch, collect_transport_step, write_transport_step
from swarm.validation import validate_discussion_dir, validate_round_file
from swarm.wal import append_message, checkpoint, finalize_round, init_discussion, resume_plan


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def emit_summary(result: dict[str, Any], summary: dict[str, Any], full: bool) -> None:
    """Print a compact summary on success; the full result on failure or --full.

    Full payloads still live in artifacts (--out/--output files, prompt-build.json,
    collect-result.json). This keeps verbose JSON out of the orchestrator context
    while preserving fail-loud behavior (errors are never truncated).
    """
    if full or not result.get("ok", False):
        emit(result)
    else:
        emit(summary)


def _visibility_counts(result: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in (result.get("visibility") or {}).values():
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def cmd_health(_args: argparse.Namespace) -> int:
    emit(
        {
            "ok": True,
            "name": "swarm-discussion-runtime",
            "version": __version__,
            "status": "skeleton",
        }
    )
    return 0


def cmd_planned_commands(_args: argparse.Namespace) -> int:
    emit({"commands": planned_commands()})
    return 0


def cmd_runtime_contract(args: argparse.Namespace) -> int:
    contract = load_runtime_contract(args.path)
    validation = validate_runtime_contract(contract)
    result = {"ok": validation["ok"], "contract": contract, "validation": validation}
    summary = {"ok": validation["ok"], "validation": validation.get("summary", {})}
    emit_summary(result, summary, args.full)
    return 0 if validation["ok"] else 1


class CliInputError(Exception):
    """Structured input failure surfaced as a JSON error result."""

    def __init__(self, issue: dict[str, Any]) -> None:
        super().__init__(issue.get("message", "invalid input"))
        self.issue = issue


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CliInputError({"code": "missing_file", "path": str(path), "message": f"missing file: {path}"}) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CliInputError({"code": "unreadable_file", "path": str(path), "message": f"cannot read file: {exc}"}) from exc
    except json.JSONDecodeError as exc:
        raise CliInputError({"code": "invalid_json", "path": str(path), "message": f"invalid JSON: {exc}"}) from exc


def load_wait_result_batches(path: Path) -> list[Any]:
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise CliInputError({"code": "missing_file", "path": str(path), "message": f"missing file: {path}"}) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CliInputError({"code": "unreadable_file", "path": str(path), "message": f"cannot read file: {exc}"}) from exc
    if path.suffix != ".jsonl":
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            pass
    batches: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            batches.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise CliInputError(
                {"code": "invalid_jsonl", "path": f"{path}:{line_number}", "message": f"invalid JSONL: {exc}"}
            ) from exc
    return batches


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text)
    os.replace(tmp_path, path)


def cmd_collect_merge(args: argparse.Namespace) -> int:
    spawn_order = load_json(args.spawn_order)
    wait_results: list[Any] = []
    for path in args.wait_result:
        wait_results.extend(load_wait_result_batches(path))
    result = collect_merge(spawn_order, wait_results)
    summary = {
        "ok": result["ok"],
        "complete": result.get("complete"),
        "timedOut": result.get("timedOut"),
        "missingAgentIds": result.get("missingAgentIds", []),
        "receivedAgentIds": result.get("receivedAgentIds", []),
        "resultCount": len(result.get("results", []) or []),
        "errors": result.get("errors", []),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_context_build(args: argparse.Namespace) -> int:
    brief = load_json(args.brief)
    result = build_context_summary(brief)
    if result["ok"] and args.out:
        write_text_atomic(args.out, result["summaryMarkdown"])
        result["summaryPath"] = str(args.out)
    summary = {
        "ok": result["ok"],
        "summarySha256": result.get("summarySha256"),
        "summary": result.get("summary", {}),
    }
    if result.get("summaryPath"):
        summary["summaryPath"] = result["summaryPath"]
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_prompt_build(args: argparse.Namespace) -> int:
    request = load_json(args.request)
    result = build_prompt(request, base_dir=args.request.parent)
    if result["ok"] and args.out_dir:
        prompt_path = args.out_dir / "prompt.txt"
        artifact_path = args.out_dir / "prompt-build.json"
        write_text_atomic(prompt_path, result["prompt"])
        write_text_atomic(artifact_path, json.dumps(result, indent=2, sort_keys=True) + "\n")
        result["artifactPaths"] = {
            "prompt": str(prompt_path),
            "promptBuild": str(artifact_path),
        }
    persona = request.get("persona") if isinstance(request, dict) else None
    summary = {
        "ok": result["ok"],
        "phase": request.get("phase") if isinstance(request, dict) else None,
        "persona": persona.get("id") if isinstance(persona, dict) else None,
        "promptSha256": result.get("promptSha256"),
        "promptCharCount": len(result.get("prompt", "") or ""),
        "visibilityCounts": _visibility_counts(result),
    }
    if result.get("artifactPaths"):
        summary["artifactPaths"] = result["artifactPaths"]
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_append_message(args: argparse.Namespace) -> int:
    result = append_message(args.dir, args.round, args.phase, load_json(args.message))
    message = result.get("message", {}) or {}
    summary = {
        "ok": result["ok"],
        "messageId": message.get("id"),
        "from": message.get("from"),
        "checkpointPath": (result.get("checkpoint") or {}).get("path"),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_checkpoint(args: argparse.Namespace) -> int:
    result = checkpoint(args.dir, args.round, args.phase, load_json(args.state))
    summary = {
        "ok": result["ok"],
        "round": result.get("round"),
        "phase": result.get("phase"),
        "path": result.get("path"),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_finalize_round(args: argparse.Namespace) -> int:
    result = finalize_round(args.dir, args.round, load_json(args.state))
    summary = {
        "ok": result["ok"],
        "round": result.get("round"),
        "path": result.get("path"),
        "warnings": result.get("warnings", []),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_init(args: argparse.Namespace) -> int:
    result = init_discussion(args.dir, args.discussion_id, mode=args.mode, title=args.title)
    summary = {
        "ok": result["ok"],
        "manifestPath": result.get("manifestPath"),
        "discussionId": result.get("discussionId"),
        "nextHelperCommand": result.get("nextHelperCommand"),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_resume_plan(args: argparse.Namespace) -> int:
    result = resume_plan(args.dir)
    emit(result)
    return 0 if result["ok"] else 1


def cmd_trace(args: argparse.Namespace) -> int:
    result = build_trace(args.dir)
    if args.output:
        write_text_atomic(args.output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {
        "ok": result["ok"],
        "health": result.get("health"),
        "nextAction": result.get("nextAction"),
        "validationOk": (result.get("validation") or {}).get("ok"),
        "validationErrorCount": len((result.get("validation") or {}).get("errors", []) or []),
    }
    if args.output:
        summary["outputPath"] = str(args.output)
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_evidence(args: argparse.Namespace) -> int:
    result = build_evidence(args.dir)
    if args.output:
        write_text_atomic(args.output, json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {
        "ok": result["ok"],
        "outcome": result.get("outcome"),
        "metrics": result.get("metrics"),
        "health": (result.get("trace") or {}).get("health"),
    }
    if args.output:
        summary["outputPath"] = str(args.output)
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_validate_host_step(args: argparse.Namespace) -> int:
    result = validate_host_transport_metadata(load_json(args.host_step))
    summary = {"ok": result["ok"], "summary": result.get("summary", {})}
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_transport_init(args: argparse.Namespace) -> int:
    result = write_transport_step(
        args.dir,
        args.host,
        args.discussion_id,
        args.round,
        args.phase,
        load_json(args.spawn_order),
        brief_path=args.brief_path,
        command_prefix=args.command_prefix,
        agent_source_dir=args.agent_source_dir,
    )
    summary = {
        "ok": result["ok"],
        "paths": result.get("paths"),
        "parentContext": (result.get("hostStep") or {}).get("parentContext"),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_transport_append_batch(args: argparse.Namespace) -> int:
    result = append_wait_batch(args.dir, args.round, args.phase, load_json(args.wait_result))
    summary = {"ok": result["ok"], "path": result.get("path")}
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_transport_collect(args: argparse.Namespace) -> int:
    result = collect_transport_step(args.dir, args.round, args.phase)
    inner = result.get("result", {}) or {}
    summary = {
        "ok": result["ok"],
        "complete": inner.get("complete"),
        "timedOut": inner.get("timedOut"),
        "missingAgentIds": inner.get("missingAgentIds", []),
        "resultCount": len(inner.get("results", []) or []),
        "collectResultPath": (result.get("paths") or {}).get("collectResultPath"),
        "errors": result.get("errors", []),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_capability_doctor(args: argparse.Namespace) -> int:
    profile_path = args.profile or default_profile_path()
    profile = load_json(profile_path)
    records = None
    evidence_base_dir = None
    errors: list[dict[str, Any]] = []
    if args.tool_evidence:
        if not args.tool_evidence.exists():
            raise CliInputError(
                {"code": "missing_file", "path": str(args.tool_evidence), "message": f"missing file: {args.tool_evidence}"}
            )
        records, errors = load_jsonl(args.tool_evidence)
        evidence_base_dir = args.tool_evidence.parent
    result = capability_doctor_report(profile, records, tool_evidence_base_dir=evidence_base_dir)
    if errors:
        result["ok"] = False
        result["errors"] = [*errors, *result["errors"]]
    tool_evidence = result.get("toolEvidence", {}) or {}
    summary = {
        "ok": result["ok"],
        "effective": result.get("effective", {}),
        "toolEvidence": {
            "recordCount": tool_evidence.get("recordCount", 0),
            "acceptedCount": tool_evidence.get("acceptedCount", 0),
            "citable": tool_evidence.get("citable", False),
        },
        "errors": result.get("errors", []),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_validate_loop(args: argparse.Namespace) -> int:
    result = validate_minimal_loop(args.discussion_dir, require_projection=args.require_projection)
    summary = {"ok": result["ok"], "summary": result.get("summary", {}), "errors": result.get("errors", [])}
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_adapter_smoke(args: argparse.Namespace) -> int:
    result = adapter_smoke(args.dir, host_step_path=args.host_step)
    summary = {"ok": result["ok"], "summary": result.get("summary", {}), "errors": result.get("errors", [])}
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_validate_round(args: argparse.Namespace) -> int:
    result = validate_round_file(args.round_path)
    summary = {
        "ok": result["ok"],
        "summary": result.get("summary", {}),
        "warningCount": len(result.get("warnings", []) or []),
        "errors": result.get("errors", []),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def cmd_validate_discussion(args: argparse.Namespace) -> int:
    result = validate_discussion_dir(args.discussion_dir)
    summary = {
        "ok": result["ok"],
        "summary": result.get("summary", {}),
        "warningCount": len(result.get("warnings", []) or []),
        "errors": result.get("errors", []),
    }
    emit_summary(result, summary, args.full)
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swarm-rt",
        description="Runtime incubator for swarm-discussion v2.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health", help="Report skeleton runtime readiness")
    health.set_defaults(func=cmd_health)

    planned = sub.add_parser("planned-commands", help="List planned runtime command surface")
    planned.set_defaults(func=cmd_planned_commands)

    contract = sub.add_parser("runtime-contract", help="Emit and validate the runtime/plugin contract")
    contract.add_argument("--path", type=Path, help="Optional runtime-contract JSON path")
    contract.set_defaults(func=cmd_runtime_contract)

    collect = sub.add_parser("collect-merge", help="Merge host wait-result batches in spawn order")
    collect.add_argument("--spawn-order", type=Path, required=True, help="JSON spawn-order list")
    collect.add_argument(
        "--wait-result",
        type=Path,
        action="append",
        required=True,
        help="JSON wait-result batch or JSONL wait-batches stream; repeat to merge partial batches",
    )
    collect.set_defaults(func=cmd_collect_merge)

    context = sub.add_parser("context-build", help="Build a compact parent-context summary")
    context.add_argument("--brief", type=Path, required=True, help="JSON parent brief")
    context.add_argument("--out", type=Path, help="Optional Markdown summary output path")
    context.set_defaults(func=cmd_context_build)

    prompt = sub.add_parser("prompt-build", help="Build an auditable prompt artifact")
    prompt.add_argument("--request", type=Path, required=True, help="JSON prompt-build request")
    prompt.add_argument("--out-dir", type=Path, help="Optional output directory for prompt artifacts")
    prompt.set_defaults(func=cmd_prompt_build)

    append = sub.add_parser("append-message", help="Mint and append one message to a round WAL")
    append.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    append.add_argument("--round", type=int, required=True, help="Round number")
    append.add_argument("--phase", required=True, help="Current phase name")
    append.add_argument("--message", type=Path, required=True, help="JSON message payload without id")
    append.set_defaults(func=cmd_append_message)

    checkpoint_cmd = sub.add_parser("checkpoint", help="Atomically write a round partial")
    checkpoint_cmd.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    checkpoint_cmd.add_argument("--round", type=int, required=True, help="Round number")
    checkpoint_cmd.add_argument("--phase", required=True, help="Current phase name")
    checkpoint_cmd.add_argument("--state", type=Path, required=True, help="JSON round state")
    checkpoint_cmd.set_defaults(func=cmd_checkpoint)

    finalize = sub.add_parser("finalize-round", help="Flush final state and promote partial to final")
    finalize.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    finalize.add_argument("--round", type=int, required=True, help="Round number")
    finalize.add_argument("--state", type=Path, required=True, help="Final round JSON state")
    finalize.set_defaults(func=cmd_finalize_round)

    resume = sub.add_parser("resume-plan", help="Describe how to resume from WAL state")
    resume.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    resume.set_defaults(func=cmd_resume_plan)

    init_p = sub.add_parser("init", help="Scaffold a discussion directory and manifest")
    init_p.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    init_p.add_argument("--discussion-id", required=True, help="Discussion id")
    init_p.add_argument("--mode", default="standard", help="Discussion mode")
    init_p.add_argument("--title", help="Optional discussion title")
    init_p.set_defaults(func=cmd_init)

    trace = sub.add_parser("trace", help="Build a diagnostic discussion artifact trace")
    trace.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    trace.add_argument("--output", type=Path, help="Optional trace JSON output path")
    trace.set_defaults(func=cmd_trace)

    evidence = sub.add_parser("evidence", help="Build portable discussion evidence")
    evidence.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    evidence.add_argument("--output", type=Path, help="Optional evidence JSON output path")
    evidence.set_defaults(func=cmd_evidence)

    validate_host_step = sub.add_parser(
        "validate-host-step",
        help="Validate thin host-adapter transport metadata",
    )
    validate_host_step.add_argument("host_step", type=Path)
    validate_host_step.set_defaults(func=cmd_validate_host_step)

    transport_init = sub.add_parser(
        "transport-init",
        help="Write spawn-order and host-step artifacts for one host adapter step",
    )
    transport_init.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    transport_init.add_argument("--host", required=True, choices=["codex", "claude"], help="Host adapter name")
    transport_init.add_argument("--discussion-id", required=True, help="Discussion id")
    transport_init.add_argument("--round", type=int, required=True, help="Round number")
    transport_init.add_argument("--phase", required=True, help="Phase name")
    transport_init.add_argument("--spawn-order", type=Path, required=True, help="JSON spawn-order list")
    transport_init.add_argument("--brief-path", default="context/summary.md", help="Brief path recorded in parent context")
    transport_init.add_argument("--command-prefix", default="swarm-rt", help="Runtime command prefix for metadata")
    transport_init.add_argument(
        "--agent-source-dir",
        default=None,
        help="Host dir holding projected custom-agent files (e.g. .claude/agents); recorded in customAgentProjection when spawn-order carries agentDescriptors",
    )
    transport_init.set_defaults(func=cmd_transport_init)

    transport_append = sub.add_parser(
        "transport-append-batch",
        help="Append one raw wait-result batch to wait-batches.jsonl",
    )
    transport_append.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    transport_append.add_argument("--round", type=int, required=True, help="Round number")
    transport_append.add_argument("--phase", required=True, help="Phase name")
    transport_append.add_argument("--wait-result", type=Path, required=True, help="JSON wait-result batch")
    transport_append.set_defaults(func=cmd_transport_append_batch)

    transport_collect = sub.add_parser(
        "transport-collect",
        help="Run collect-merge from transport artifacts and write collect-result.json",
    )
    transport_collect.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    transport_collect.add_argument("--round", type=int, required=True, help="Round number")
    transport_collect.add_argument("--phase", required=True, help="Phase name")
    transport_collect.set_defaults(func=cmd_transport_collect)

    capability = sub.add_parser(
        "capability-doctor",
        help="Report effective expert capability profile and evidence citation status",
    )
    capability.add_argument("--profile", type=Path, help="Capability profile JSON path")
    capability.add_argument("--tool-evidence", type=Path, help="Optional tool-evidence JSONL path")
    capability.set_defaults(func=cmd_capability_doctor)

    validate_loop = sub.add_parser(
        "validate-loop",
        help="Validate the smallest complete v2 discussion artifact loop",
    )
    validate_loop.add_argument("discussion_dir", type=Path)
    validate_loop.add_argument(
        "--require-projection",
        action="store_true",
        help="Fail unless the discussion declares projected custom agents with consistent provenance (v0.3.0 release mode; ADR 0001 D4)",
    )
    validate_loop.set_defaults(func=cmd_validate_loop)

    smoke = sub.add_parser(
        "adapter-smoke",
        help="Smoke-check host adapter artifacts without spawning agents",
    )
    smoke.add_argument("--dir", type=Path, required=True, help="Discussion artifact directory")
    smoke.add_argument("--host-step", type=Path, help="Optional host-step path relative to --dir")
    smoke.set_defaults(func=cmd_adapter_smoke)

    validate_round = sub.add_parser("validate-round", help="Validate one committed round JSON file")
    validate_round.add_argument("round_path", type=Path)
    validate_round.set_defaults(func=cmd_validate_round)

    validate_discussion = sub.add_parser(
        "validate-discussion", help="Validate a discussion artifact directory"
    )
    validate_discussion.add_argument("discussion_dir", type=Path)
    validate_discussion.set_defaults(func=cmd_validate_discussion)

    # Every subcommand prints a compact summary by default; --full restores the
    # full JSON result. Failures always print the full result regardless.
    for subparser in sub.choices.values():
        subparser.add_argument(
            "--full",
            action="store_true",
            help="Print the full JSON result instead of the compact summary",
        )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliInputError as exc:
        emit({"ok": False, "errors": [exc.issue]})
        return 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        emit(
            {
                "ok": False,
                "errors": [
                    {
                        "code": "invalid_input",
                        "path": str(getattr(exc, "filename", "") or ""),
                        "message": str(exc),
                    }
                ],
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
