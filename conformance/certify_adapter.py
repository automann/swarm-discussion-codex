#!/usr/bin/env python3
"""Certify a retained Codex smoke discussion against the vendored runtime.

The runtime owns protocol validation. This script adds only the adapter-level
release checks that the generic runtime gates cannot know: retained smoke
location, vendored bundle integrity, and host transport evidence that rejects a
fixture-only proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_GATES = (
    "runtime-contract",
    "vendor-manifest",
    "adapter-smoke",
    "validate-loop",
    "validate-discussion",
)
FIXTURE_AGENT_IDS = {"agent-architect", "agent-contrarian"}


def issue(code: str, path: str, message: str, value: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "path": path, "message": message}
    if value is not None:
        payload["value"] = value
    return payload


def load_json(path: Path, errors: list[dict[str, Any]], label: str | None = None) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        errors.append(issue("missing_file", label or str(path), f"missing file: {path}"))
    except json.JSONDecodeError as exc:
        errors.append(issue("invalid_json", label or str(path), f"invalid JSON: {exc}"))
    return None


def load_jsonl(path: Path, errors: list[dict[str, Any]], label: str | None = None) -> list[Any]:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        errors.append(issue("missing_file", label or str(path), f"missing file: {path}"))
        return []
    records: list[Any] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(issue("invalid_jsonl", f"{label or path}:{line_number}", f"invalid JSONL: {exc}"))
    return records


def relative_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_payload(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_json_gate(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = read_payload(proc.stdout)
    payload_ok = isinstance(payload, dict) and payload.get("ok") is not False
    ok = proc.returncode == 0 and payload_ok
    errors: list[dict[str, Any]] = []
    if proc.returncode != 0:
        errors.append(issue("command_failed", name, f"{name} exited {proc.returncode}"))
    if payload is None:
        errors.append(issue("missing_json_output", name, f"{name} did not emit JSON"))
    elif not isinstance(payload, dict):
        errors.append(issue("invalid_json_output", name, f"{name} output must be a JSON object"))
    elif payload.get("ok") is False:
        errors.extend(payload.get("errors") or [issue("gate_not_ok", name, f"{name} returned ok=false")])
    return {
        "name": name,
        "ok": ok,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "payload": payload,
        "errors": errors,
    }


def verify_vendor_manifest(vendored: Path, runtime: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    manifest_path = vendored / "vendor-manifest.json"
    manifest = load_json(manifest_path, errors, "vendor-manifest.json")
    if not vendored.is_dir():
        errors.append(issue("missing_vendored_runtime", str(vendored), "vendored runtime directory does not exist"))
    if not runtime.is_file():
        errors.append(issue("missing_runtime_cli", str(runtime), "runtime CLI does not exist"))
    else:
        try:
            runtime.resolve().relative_to(vendored.resolve())
        except ValueError:
            errors.append(issue("runtime_outside_vendor", str(runtime), "runtime CLI must live under --vendored"))

    file_count = 0
    runtime_sha = None
    if isinstance(manifest, dict):
        if manifest.get("kind") != "swarm.vendor_manifest":
            errors.append(issue("invalid_manifest_kind", "vendor-manifest.json:kind", "unexpected manifest kind", manifest.get("kind")))
        runtime_sha = manifest.get("runtimeSha")
        files = manifest.get("files")
        if not isinstance(files, dict):
            errors.append(issue("invalid_manifest_files", "vendor-manifest.json:files", "files must be an object"))
            files = {}
        file_count = len(files)
        if manifest.get("fileCount") != file_count:
            errors.append(
                issue(
                    "file_count_mismatch",
                    "vendor-manifest.json:fileCount",
                    "fileCount must match files length",
                    {"declared": manifest.get("fileCount"), "actual": file_count},
                )
            )
        for rel_path, expected_sha in sorted(files.items()):
            if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
                errors.append(issue("invalid_manifest_entry", str(rel_path), "manifest entries must be string paths and hashes"))
                continue
            path = Path(rel_path)
            if path.is_absolute() or ".." in path.parts:
                errors.append(issue("unsafe_manifest_path", rel_path, "manifest path must stay inside --vendored"))
                continue
            file_path = vendored / path
            if not file_path.is_file():
                errors.append(issue("missing_vendored_file", rel_path, "manifest file is missing"))
                continue
            actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_sha != expected_sha:
                errors.append(
                    issue(
                        "vendored_file_drift",
                        rel_path,
                        "manifest hash does not match vendored file",
                        {"expected": expected_sha, "actual": actual_sha},
                    )
                )

    return {
        "name": "vendor-manifest",
        "ok": not errors,
        "path": str(manifest_path),
        "fileCount": file_count,
        "runtimeSha": runtime_sha,
        "errors": errors,
    }


def check_required_file(root: Path, rel_path: str, errors: list[dict[str, Any]], non_empty: bool = False) -> None:
    path = root / rel_path
    if not path.is_file():
        errors.append(issue("missing_required_artifact", rel_path, f"missing required artifact: {rel_path}"))
        return
    if non_empty and not path.read_text(errors="replace").strip():
        errors.append(issue("empty_required_artifact", rel_path, f"required artifact is empty: {rel_path}"))


def resolve_artifact(root: Path, value: Any, errors: list[dict[str, Any]], label: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(issue("missing_artifact_path", label, "artifact path must be a non-empty string"))
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        errors.append(issue("unsafe_artifact_path", label, "artifact path must be relative to the discussion directory", value))
        return None
    resolved = root / path
    if not resolved.is_file():
        errors.append(issue("missing_artifact_path", label, f"artifact file does not exist: {value}"))
        return None
    return resolved


def host_transport_checks(discussion: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    spawn_agent_ids: set[str] = set()
    wait_agent_ids: set[str] = set()
    host_step_paths = sorted((discussion / "transport").glob("**/host-step.json"))
    if not host_step_paths:
        errors.append(issue("missing_host_step", "transport", "no host-step.json found"))

    for host_step_path in host_step_paths:
        label = relative_to(host_step_path, discussion)
        host_step = load_json(host_step_path, errors, label)
        if not isinstance(host_step, dict):
            continue

        if host_step.get("host") != "codex":
            errors.append(issue("invalid_host", f"{label}:host", "host-step host must be codex", host_step.get("host")))
        transport = host_step.get("transport") if isinstance(host_step.get("transport"), dict) else {}
        if "spawn_agent" not in str(transport.get("spawnPrimitive", "")):
            errors.append(issue("missing_spawn_primitive", f"{label}:transport.spawnPrimitive", "spawn primitive must be recorded"))
        if "wait_agent" not in str(transport.get("waitPrimitive", "")):
            errors.append(issue("missing_wait_primitive", f"{label}:transport.waitPrimitive", "wait primitive must be recorded"))

        parent_context = host_step.get("parentContext") if isinstance(host_step.get("parentContext"), dict) else {}
        parent_agent_ids = parent_context.get("agentIds") if isinstance(parent_context.get("agentIds"), list) else []
        for agent_id in parent_agent_ids:
            if isinstance(agent_id, str) and agent_id.strip():
                spawn_agent_ids.add(agent_id)

        artifacts = host_step.get("artifacts") if isinstance(host_step.get("artifacts"), dict) else {}
        spawn_order_path = resolve_artifact(discussion, artifacts.get("spawnOrderPath"), errors, f"{label}:artifacts.spawnOrderPath")
        wait_batches_path = resolve_artifact(discussion, artifacts.get("waitBatchesPath"), errors, f"{label}:artifacts.waitBatchesPath")
        collect_result_path = resolve_artifact(discussion, artifacts.get("collectResultPath"), errors, f"{label}:artifacts.collectResultPath")

        if spawn_order_path:
            spawn_order = load_json(spawn_order_path, errors, relative_to(spawn_order_path, discussion))
            if not isinstance(spawn_order, list) or not spawn_order:
                errors.append(issue("invalid_spawn_order", relative_to(spawn_order_path, discussion), "spawn order must be a non-empty list"))
            else:
                for index, item in enumerate(spawn_order):
                    if not isinstance(item, dict):
                        errors.append(issue("invalid_spawn_order_entry", f"{relative_to(spawn_order_path, discussion)}[{index}]", "spawn order item must be an object"))
                        continue
                    agent_id = item.get("agentId")
                    persona = item.get("persona")
                    if not isinstance(agent_id, str) or not agent_id.strip():
                        errors.append(issue("missing_agent_id", f"{relative_to(spawn_order_path, discussion)}[{index}].agentId", "agentId is required"))
                    else:
                        spawn_agent_ids.add(agent_id)
                    if not isinstance(persona, str) or not persona.strip():
                        errors.append(issue("missing_persona", f"{relative_to(spawn_order_path, discussion)}[{index}].persona", "persona is required"))

        if wait_batches_path:
            batches = load_jsonl(wait_batches_path, errors, relative_to(wait_batches_path, discussion))
            if not batches:
                errors.append(issue("missing_wait_batch", relative_to(wait_batches_path, discussion), "wait-batches.jsonl must contain at least one batch"))
            for batch_index, batch in enumerate(batches):
                if not isinstance(batch, dict):
                    errors.append(issue("invalid_wait_batch", f"{relative_to(wait_batches_path, discussion)}:{batch_index + 1}", "wait batch must be an object"))
                    continue
                status = batch.get("status") if isinstance(batch.get("status"), dict) else {}
                for agent_id, record in status.items():
                    if isinstance(agent_id, str):
                        wait_agent_ids.add(agent_id)
                    if isinstance(record, dict) and "completed" in record and not str(record.get("completed", "")).strip():
                        errors.append(issue("empty_completed_result", f"{relative_to(wait_batches_path, discussion)}:{agent_id}", "completed result must be non-empty"))

        if collect_result_path:
            collect_result = load_json(collect_result_path, errors, relative_to(collect_result_path, discussion))
            if isinstance(collect_result, dict):
                if collect_result.get("ok") is not True or collect_result.get("complete") is not True:
                    errors.append(issue("incomplete_collect_result", relative_to(collect_result_path, discussion), "collect-result must be ok and complete"))
                received = collect_result.get("receivedAgentIds")
                if not isinstance(received, list) or not received:
                    errors.append(issue("missing_received_agent_ids", relative_to(collect_result_path, discussion), "collect-result must list received agent ids"))
                else:
                    for agent_id in received:
                        if isinstance(agent_id, str):
                            wait_agent_ids.add(agent_id)
                results = collect_result.get("results")
                if not isinstance(results, list) or not results:
                    errors.append(issue("missing_collect_results", relative_to(collect_result_path, discussion), "collect-result must include normalized results"))

    if not spawn_agent_ids:
        errors.append(issue("missing_agent_ids", "transport", "no Codex agent ids recorded"))
    if spawn_agent_ids & FIXTURE_AGENT_IDS:
        errors.append(
            issue(
                "fixture_agent_ids",
                "transport",
                "fixture agent ids are not acceptable retained Codex smoke evidence",
                sorted(spawn_agent_ids & FIXTURE_AGENT_IDS),
            )
        )
    missing_wait = sorted(spawn_agent_ids - wait_agent_ids)
    if missing_wait:
        errors.append(issue("missing_wait_results", "transport", "spawned agent ids must appear in wait/collect evidence", missing_wait))

    return {
        "name": "codex-host-transport",
        "ok": not errors,
        "hostStepCount": len(host_step_paths),
        "agentIds": sorted(spawn_agent_ids),
        "waitAgentIds": sorted(wait_agent_ids),
        "errors": errors,
    }


def smoke_tree_checks(discussion: Path, repo_root: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    smoke_root = (repo_root / "smoke" / "discussions").resolve()
    try:
        discussion.resolve().relative_to(smoke_root)
    except ValueError:
        errors.append(issue("discussion_outside_smoke_root", str(discussion), "discussion must live under smoke/discussions"))

    manifest = load_json(discussion / "manifest.json", errors, "manifest.json")
    if isinstance(manifest, dict):
        if manifest.get("id") == "minimal-v2":
            errors.append(issue("fixture_discussion_id", "manifest.json:id", "vendored fixture id is not retained smoke evidence"))
        mode = manifest.get("mode")
        if not isinstance(mode, str) or "smoke" not in mode:
            errors.append(issue("invalid_smoke_mode", "manifest.json:mode", "retained certification discussion mode must include smoke", mode))
        if manifest.get("status") not in {"completed", "complete", "done"}:
            errors.append(issue("discussion_not_complete", "manifest.json:status", "retained smoke discussion must be complete", manifest.get("status")))

    check_required_file(discussion, "context/summary.md", errors, non_empty=True)
    check_required_file(discussion, "rounds/001.json", errors)
    check_required_file(discussion, "artifacts/synthesis.md", errors, non_empty=True)
    check_required_file(discussion, "artifacts/trace.json", errors)
    check_required_file(discussion, "artifacts/evidence.json", errors)
    check_required_file(discussion, "capabilities/profile.json", errors)
    check_required_file(discussion, "capabilities/tool-evidence.jsonl", errors, non_empty=True)

    prompt_artifacts = sorted((discussion / "prompts").glob("**/prompt-build.json"))
    if not prompt_artifacts:
        errors.append(issue("missing_prompt_artifact", "prompts", "at least one prompt-build artifact is required"))

    trace = load_json(discussion / "artifacts" / "trace.json", errors, "artifacts/trace.json")
    if isinstance(trace, dict):
        if trace.get("health") != "on-track":
            errors.append(issue("trace_not_on_track", "artifacts/trace.json:health", "trace health must be on-track", trace.get("health")))
        transport = trace.get("transport") if isinstance(trace.get("transport"), dict) else {}
        if transport.get("complete") is not True:
            errors.append(issue("trace_transport_incomplete", "artifacts/trace.json:transport", "trace transport must be complete"))

    evidence = load_json(discussion / "artifacts" / "evidence.json", errors, "artifacts/evidence.json")
    if isinstance(evidence, dict):
        if evidence.get("kind") != "swarm.discussion_evidence":
            errors.append(issue("invalid_evidence_kind", "artifacts/evidence.json:kind", "unexpected evidence kind", evidence.get("kind")))
        outcome = evidence.get("outcome") if isinstance(evidence.get("outcome"), dict) else {}
        if outcome.get("result") not in {"completed", "complete", "done"}:
            errors.append(issue("evidence_not_complete", "artifacts/evidence.json:outcome.result", "evidence outcome must be complete", outcome.get("result")))

    transport = host_transport_checks(discussion)
    errors.extend(transport["errors"])

    return {
        "name": "retained-smoke-evidence",
        "ok": not errors,
        "discussion": str(discussion),
        "promptBuildCount": len(prompt_artifacts),
        "transport": transport,
        "errors": errors,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Certify a retained Codex adapter smoke discussion.")
    parser.add_argument("--discussion", required=True, type=Path, help="Retained smoke discussion directory")
    parser.add_argument("--vendored", required=True, type=Path, help="Vendored swarm runtime root")
    parser.add_argument("--runtime", required=True, type=Path, help="Vendored runtime CLI path")
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    discussion = args.discussion.resolve()
    vendored = args.vendored.resolve()
    runtime = args.runtime.resolve()
    runtime_cmd = [sys.executable, str(runtime)]
    smoke_root = (repo_root / "smoke" / "discussions").resolve()
    retained_smoke_path = False
    try:
        discussion.relative_to(smoke_root)
        retained_smoke_path = True
    except ValueError:
        retained_smoke_path = False

    pre_gate_refresh: dict[str, Any] = {}
    if discussion.is_dir() and retained_smoke_path:
        trace_gate = run_json_gate(
            "trace",
            [*runtime_cmd, "trace", "--dir", str(discussion), "--output", str(discussion / "artifacts" / "trace.json"), "--full"],
            repo_root,
        )
        evidence_rebuild_gate = run_json_gate(
            "evidence",
            [
                *runtime_cmd,
                "evidence",
                "--dir",
                str(discussion),
                "--output",
                str(discussion / "artifacts" / "evidence.json"),
                "--full",
            ],
            repo_root,
        )
        pre_gate_refresh = {
            "trace": {key: value for key, value in trace_gate.items() if key not in {"stdout", "stderr", "payload"}},
            "evidence": {
                key: value for key, value in evidence_rebuild_gate.items() if key not in {"stdout", "stderr", "payload"}
            },
        }

    gates: dict[str, Any] = {}
    vendor_gate = verify_vendor_manifest(vendored, runtime)
    gates["vendor-manifest"] = vendor_gate
    gates["runtime-contract"] = run_json_gate("runtime-contract", [*runtime_cmd, "runtime-contract", "--full"], repo_root)
    gates["adapter-smoke"] = run_json_gate("adapter-smoke", [*runtime_cmd, "adapter-smoke", "--dir", str(discussion), "--full"], repo_root)
    gates["validate-loop"] = run_json_gate("validate-loop", [*runtime_cmd, "validate-loop", str(discussion), "--full"], repo_root)
    gates["validate-discussion"] = run_json_gate("validate-discussion", [*runtime_cmd, "validate-discussion", str(discussion), "--full"], repo_root)

    evidence_gate = smoke_tree_checks(discussion, repo_root)

    required_gate_status = {name: bool(gates[name].get("ok")) for name in REQUIRED_GATES}
    all_ok = all(required_gate_status.values()) and evidence_gate["ok"]
    summary = {
        "schemaVersion": 1,
        "kind": "swarm.codex_adapter_certification",
        "ok": all_ok,
        "discussion": str(discussion),
        "discussionRelative": relative_to(discussion, repo_root),
        "vendored": str(vendored),
        "runtime": str(runtime),
        "requiredGates": required_gate_status,
        "adapterEvidence": evidence_gate,
        "preGateRefresh": pre_gate_refresh,
        "gates": {
            name: {
                key: value
                for key, value in gate.items()
                if key not in {"stdout", "stderr", "payload"}
            }
            for name, gate in gates.items()
        },
    }

    exit_ok = all_ok
    output_summary = dict(summary)
    if discussion.is_dir() and retained_smoke_path:
        write_json(discussion / "certification" / "adapter-certification.json", summary)
        trace_gate = run_json_gate(
            "trace",
            [*runtime_cmd, "trace", "--dir", str(discussion), "--output", str(discussion / "artifacts" / "trace.json"), "--full"],
            repo_root,
        )
        evidence_rebuild_gate = run_json_gate(
            "evidence",
            [
                *runtime_cmd,
                "evidence",
                "--dir",
                str(discussion),
                "--output",
                str(discussion / "artifacts" / "evidence.json"),
                "--full",
            ],
            repo_root,
        )
        post_adapter_smoke = run_json_gate(
            "adapter-smoke", [*runtime_cmd, "adapter-smoke", "--dir", str(discussion), "--full"], repo_root
        )
        post_loop = run_json_gate("validate-loop", [*runtime_cmd, "validate-loop", str(discussion), "--full"], repo_root)
        post_discussion = run_json_gate(
            "validate-discussion", [*runtime_cmd, "validate-discussion", str(discussion), "--full"], repo_root
        )
        output_summary = dict(summary)
        output_summary["postCertificationRefresh"] = {
            "trace": {key: value for key, value in trace_gate.items() if key not in {"stdout", "stderr", "payload"}},
            "evidence": {
                key: value for key, value in evidence_rebuild_gate.items() if key not in {"stdout", "stderr", "payload"}
            },
            "adapter-smoke": {
                key: value for key, value in post_adapter_smoke.items() if key not in {"stdout", "stderr", "payload"}
            },
            "validate-loop": {key: value for key, value in post_loop.items() if key not in {"stdout", "stderr", "payload"}},
            "validate-discussion": {
                key: value for key, value in post_discussion.items() if key not in {"stdout", "stderr", "payload"}
            },
        }
        exit_ok = (
            summary["ok"]
            and trace_gate["ok"]
            and evidence_rebuild_gate["ok"]
            and post_adapter_smoke["ok"]
            and post_loop["ok"]
            and post_discussion["ok"]
        )
        output_summary["ok"] = exit_ok

    print(json.dumps(output_summary, indent=2, sort_keys=True))
    return 0 if exit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
