#!/usr/bin/env python3
"""Thin Codex-side wrapper for the v2 swarm runtime contract.

The wrapper deliberately contains no discussion mechanics. It discovers the
vendored runtime CLI, checks the runtime contract, reports host diagnostics, and
delegates runtime commands while preserving runtime exit codes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ENV_RUNTIME = "SWARM_DISCUSSION_RUNTIME"
COMPATIBILITY = "swarm-runtime-v2-alpha"
ADAPTER_SMOKE = "adapter-smoke"
RUNTIME_CONTRACT = "runtime-contract"
VALIDATE_LOOP = "validate-loop"
NORMAL_DISCUSSION_ROOT = ".swarm/discussions"
SMOKE_DISCUSSION_ROOT = "smoke/discussions"
REQUIRED_CERTIFICATION_GATES = [
    RUNTIME_CONTRACT,
    "vendor-manifest",
    ADAPTER_SMOKE,
    VALIDATE_LOOP,
    "validate-discussion",
]
VENDOR_SUBDIR = ("vendor", "swarm-runtime")
BUNDLED_CLI = (*VENDOR_SUBDIR, "runtime", "swarm_rt.py")
VENDOR_MANIFEST = (*VENDOR_SUBDIR, "vendor-manifest.json")
FIXTURE_REL = (*VENDOR_SUBDIR, "fixtures", "e2e", "minimal-v2")
PRIMITIVE_COMMANDS = [
    "context-build",
    "prompt-build",
    "collect-merge",
    "transport-init",
    "transport-append-batch",
    "transport-collect",
    "append-message",
    "checkpoint",
    "finalize-round",
    "resume-plan",
    "validate-round",
    "validate-discussion",
    "trace",
    "evidence",
    "validate-host-step",
    "capability-doctor",
    "init",
]


class WrapperError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_error(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        error.update({key: value for key, value in self.details.items() if value is not None})
        return error


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def display_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def command_from_string(value: str, source: str) -> list[str]:
    try:
        parts = shlex.split(value)
    except ValueError as exc:
        raise WrapperError(
            "runtime_command_parse_error",
            f"{source} runtime command could not be parsed: {exc}",
            source=source,
        ) from exc
    if not parts:
        raise WrapperError("runtime_command_empty", f"{source} runtime command is empty", source=source)
    first = Path(parts[0]).expanduser()
    if first.suffix == ".py" and first.exists():
        return [sys.executable, str(first), *parts[1:]]
    if first.exists():
        return [str(first), *parts[1:]]
    return parts


def runtime_candidates(explicit: str | None) -> list[dict[str, Any]]:
    if explicit is not None:
        return [
            {
                "source": "--runtime",
                "command": command_from_string(explicit, "--runtime"),
                "strict": True,
                "errorCode": "runtime_override_invalid",
            }
        ]

    env_value = os.environ.get(ENV_RUNTIME)
    if env_value:
        return [
            {
                "source": ENV_RUNTIME,
                "command": command_from_string(env_value, ENV_RUNTIME),
                "strict": True,
                "errorCode": "runtime_env_invalid",
            }
        ]

    candidates: list[dict[str, Any]] = []
    bundled = plugin_root().joinpath(*BUNDLED_CLI)
    if bundled.exists():
        candidates.append({"source": "vendored", "command": [sys.executable, str(bundled)], "strict": False})

    path_runtime = shutil.which("swarm-rt")
    if path_runtime:
        candidates.append({"source": "PATH", "command": [path_runtime], "strict": False})

    seen: set[tuple[str, ...]] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = tuple(candidate["command"])
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def run(command: list[str], args: list[str]) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    try:
        completed = subprocess.run(
            [*command, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc), "json": None}

    parsed: Any | None = None
    if completed.stdout.strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "json": parsed,
    }


def contract_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return ["runtime-contract did not return an ok JSON object"]
    contract = payload.get("contract")
    if not isinstance(contract, dict):
        return ["contract must be a JSON object"]
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("compatibility") != COMPATIBILITY:
        errors.append(f"contract.runtime.compatibility must be {COMPATIBILITY}")
    commands = contract.get("commands")
    if not isinstance(commands, dict):
        errors.append("contract.commands must be a JSON object")
    else:
        required = {ADAPTER_SMOKE, VALIDATE_LOOP, *PRIMITIVE_COMMANDS}
        missing = sorted(required - set(commands))
        if missing:
            errors.append(f"contract.commands missing required commands: {', '.join(missing)}")
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        errors.append("validation must be a JSON object")
    elif validation.get("ok") is not True:
        errors.append("validation.ok must be true")
    return errors


def contract_ok(payload: Any) -> bool:
    return not contract_errors(payload)


def contract_summary(payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        return {}
    summary = validation.get("summary")
    return summary if isinstance(summary, dict) else {}


def plugin_fixture_dir() -> Path:
    return plugin_root().joinpath(*FIXTURE_REL)


def vendor_manifest_path() -> Path:
    return plugin_root().joinpath(*VENDOR_MANIFEST)


def _path_status(rel_path: str, sprint_row: str) -> dict[str, Any]:
    exists = plugin_root().joinpath(rel_path).exists()
    return {
        "path": rel_path,
        "exists": exists,
        "status": "present" if exists else "planned",
        "sprintRow": sprint_row,
    }


def artifact_paths() -> dict[str, Any]:
    """Report adapter artifact roots; the wrapper never creates them."""
    return {
        "normalDiscussionRoot": NORMAL_DISCUSSION_ROOT,
        "normalDiscussionPattern": f"{NORMAL_DISCUSSION_ROOT}/<id>",
        "smokeDiscussionRoot": SMOKE_DISCUSSION_ROOT,
        "smokeDiscussionPattern": f"{SMOKE_DISCUSSION_ROOT}/<id>",
        "requiredCertificationGates": REQUIRED_CERTIFICATION_GATES,
        "wrapperCreatesDiscussionDirs": False,
        "normalOwner": "coordinator-runtime-init",
        "smokeOwner": "release-smoke-coordinator-run",
    }


def host_diagnostics() -> dict[str, Any]:
    """Report Codex host facts without probing or managing threads."""
    return {
        "host": "codex",
        "topology": "thread-coordinator",
        "wrapperManagesThreads": False,
        "threadLifecycleOwner": _path_status("skills/swarm-discussion/SKILL.md", "parent-skill-thread-lifecycle"),
        "coordinatorContract": _path_status(
            "agents/swarm-coordinator.toml",
            "coordinator-and-expert-agent-contracts",
        ),
        "nestedSubagentTopology": {
            "supported": None,
            "usedByV1": False,
            "reason": "doctor is non-mutating; v1 always uses a dedicated coordinator thread",
        },
    }


def verify_vendor_manifest() -> dict[str, Any]:
    manifest_path = vendor_manifest_path()
    runtime_root = plugin_root().joinpath(*VENDOR_SUBDIR)
    errors: list[dict[str, Any]] = []

    if not manifest_path.exists():
        return {"ok": False, "path": str(manifest_path), "fileCount": 0, "errors": [{"code": "missing_manifest"}]}

    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "path": str(manifest_path),
            "fileCount": 0,
            "errors": [{"code": "invalid_manifest_json", "message": str(exc)}],
        }

    if not isinstance(manifest, dict):
        return {
            "ok": False,
            "path": str(manifest_path),
            "fileCount": 0,
            "errors": [{"code": "invalid_manifest", "message": "manifest must be a JSON object"}],
        }

    if manifest.get("kind") != "swarm.vendor_manifest":
        errors.append({"code": "invalid_manifest_kind", "value": manifest.get("kind")})

    files = manifest.get("files")
    if not isinstance(files, dict):
        errors.append({"code": "invalid_manifest_files", "message": "files must be a JSON object"})
        files = {}

    for rel_path, expected_sha in sorted(files.items()):
        if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
            errors.append({"code": "invalid_manifest_entry", "path": str(rel_path)})
            continue
        path = Path(rel_path)
        if path.is_absolute() or ".." in path.parts:
            errors.append({"code": "unsafe_manifest_path", "path": rel_path})
            continue
        file_path = runtime_root / path
        if not file_path.is_file():
            errors.append({"code": "missing_vendored_file", "path": rel_path})
            continue
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            errors.append(
                {
                    "code": "vendored_file_drift",
                    "path": rel_path,
                    "expected": expected_sha,
                    "actual": actual_sha,
                }
            )

    return {
        "ok": not errors,
        "path": str(manifest_path),
        "runtimeSha": manifest.get("runtimeSha"),
        "fileCount": len(files),
        "errors": errors,
    }


def resolve_runtime(explicit: str | None) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    try:
        candidates = runtime_candidates(explicit)
    except WrapperError as exc:
        return {"ok": False, "errors": [exc.as_error()], "attempts": attempts}

    for candidate in candidates:
        manifest: dict[str, Any] | None = None
        if candidate["source"] == "vendored":
            manifest = verify_vendor_manifest()
            if not manifest["ok"]:
                attempts.append(
                    {
                        "source": candidate["source"],
                        "command": display_command(candidate["command"]),
                        "returncode": None,
                        "contractOk": False,
                        "contractErrors": ["vendor manifest verification failed"],
                        "vendorManifestOk": False,
                        "stderr": "",
                    }
                )
                return {
                    "ok": False,
                    "errors": [
                        {
                            "code": "vendor_manifest_invalid",
                            "message": "vendored runtime manifest verification failed",
                        }
                    ],
                    "attempts": attempts,
                    "vendorManifest": manifest,
                }
        result = run(candidate["command"], [RUNTIME_CONTRACT, "--full"])
        payload = result["json"]
        errors = contract_errors(payload)
        attempts.append(
            {
                "source": candidate["source"],
                "command": display_command(candidate["command"]),
                "returncode": result["returncode"],
                "contractOk": not errors,
                "contractErrors": errors,
                "stderr": result["stderr"].strip(),
            }
        )
        if result["ok"] and not errors:
            return {
                "ok": True,
                "runtime": {
                    "source": candidate["source"],
                    "command": candidate["command"],
                    "display": display_command(candidate["command"]),
                },
                "contract": payload,
                "attempts": attempts,
                "vendorManifest": manifest,
            }
        if candidate.get("strict"):
            return {
                "ok": False,
                "errors": [
                    {
                        "code": candidate["errorCode"],
                        "message": f"{candidate['source']} did not provide a valid {COMPATIBILITY} runtime.",
                        "source": candidate["source"],
                        "contractErrors": errors,
                    }
                ],
                "attempts": attempts,
            }

    return {
        "ok": False,
        "errors": [
            {
                "code": "runtime_not_found",
                "message": (
                    f"Set {ENV_RUNTIME}, pass --runtime, vendor the runtime under "
                    "vendor/swarm-runtime, or install swarm-rt on PATH."
                ),
            }
        ],
        "attempts": attempts,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    resolved = resolve_runtime(args.runtime)
    ok = resolved["ok"]
    payload: dict[str, Any] = {
        "ok": ok,
        "wrapper": {
            "kind": "swarm.codex_runtime_wrapper",
            "compatibility": COMPATIBILITY,
            "path": str(Path(__file__).resolve()),
            "pluginRoot": str(plugin_root()),
            "fixtureDir": str(plugin_fixture_dir()),
        },
        "artifactPaths": artifact_paths(),
        "hostDiagnostics": host_diagnostics(),
        "attempts": resolved["attempts"],
    }
    if "vendorManifest" in resolved and resolved["vendorManifest"] is not None:
        payload["vendorManifest"] = resolved["vendorManifest"]
    if resolved["ok"]:
        payload["runtime"] = {
            "source": resolved["runtime"]["source"],
            "command": resolved["runtime"]["display"],
        }
        payload["contractSummary"] = contract_summary(resolved["contract"])
        if args.smoke_fixture and ok:
            fixture_dir = plugin_fixture_dir()
            smoke = run(resolved["runtime"]["command"], [ADAPTER_SMOKE, "--dir", str(fixture_dir)])
            smoke_json = smoke["json"] if isinstance(smoke["json"], dict) else {}
            payload["fixtureSmoke"] = {
                "ok": smoke["ok"],
                "dir": str(fixture_dir),
                "returncode": smoke["returncode"],
                "summary": smoke_json.get("summary"),
                "errors": smoke_json.get("errors"),
                "stderr": smoke["stderr"].strip(),
            }
            ok = ok and smoke["ok"]
            payload["ok"] = ok
        elif args.smoke_fixture:
            payload["fixtureSmoke"] = {
                "ok": False,
                "skipped": True,
                "reason": "runtime or vendored manifest check failed before fixture smoke",
            }
    else:
        payload["errors"] = resolved["errors"]
    emit(payload)
    return 0 if ok else 1


def _runtime_exit(result: dict[str, Any]) -> int:
    return result["returncode"] if isinstance(result["returncode"], int) else 1


def _delegate(args: argparse.Namespace, runtime_args: list[str]) -> int:
    resolved = resolve_runtime(args.runtime)
    if not resolved["ok"]:
        payload = {"ok": False, "errors": resolved["errors"], "attempts": resolved["attempts"]}
        if "vendorManifest" in resolved:
            payload["vendorManifest"] = resolved["vendorManifest"]
        emit(payload)
        return 1
    result = run(resolved["runtime"]["command"], runtime_args)
    emit(
        {
            "ok": result["ok"],
            "wrapper": {"compatibility": COMPATIBILITY},
            "runtime": {
                "source": resolved["runtime"]["source"],
                "command": resolved["runtime"]["display"],
                "args": runtime_args,
                "returncode": result["returncode"],
            },
            "result": result["json"],
            "stdout": None if result["json"] is not None else result["stdout"],
            "stderr": result["stderr"].strip(),
        }
    )
    return _runtime_exit(result)


def cmd_runtime_contract(args: argparse.Namespace) -> int:
    resolved = resolve_runtime(args.runtime)
    if not resolved["ok"]:
        payload = {"ok": False, "errors": resolved["errors"], "attempts": resolved["attempts"]}
        if "vendorManifest" in resolved:
            payload["vendorManifest"] = resolved["vendorManifest"]
        emit(payload)
        return 1
    contract = resolved["contract"].get("contract")
    validation = resolved["contract"].get("validation")
    if not isinstance(contract, dict) or not isinstance(validation, dict):
        emit(
            {
                "ok": False,
                "errors": [
                    {
                        "code": "runtime_contract_invalid",
                        "message": "validated runtime contract payload is incomplete",
                    }
                ],
                "attempts": resolved["attempts"],
            }
        )
        return 1
    emit(
        {
            "ok": True,
            "wrapper": {"compatibility": COMPATIBILITY},
            "runtime": {
                "source": resolved["runtime"]["source"],
                "command": resolved["runtime"]["display"],
            },
            "contract": contract,
            "validation": validation,
        }
    )
    return 0


def cmd_adapter_smoke(args: argparse.Namespace) -> int:
    runtime_args = [ADAPTER_SMOKE, "--dir", str(args.dir)]
    if args.host_step:
        runtime_args.extend(["--host-step", str(args.host_step)])
    return _delegate(args, runtime_args)


def cmd_validate_loop(args: argparse.Namespace) -> int:
    return _delegate(args, [VALIDATE_LOOP, str(args.dir)])


def cmd_runtime_primitive(args: argparse.Namespace) -> int:
    return _delegate(args, [args.runtime_command, *args.runtime_args])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swarm-runtime-wrapper",
        description="Resolve and delegate to the vendored v2 swarm runtime CLI.",
        epilog="Delegated runtime commands: " + ", ".join(PRIMITIVE_COMMANDS),
    )
    parser.add_argument("--runtime", help=f"Runtime command override. Also supported through {ENV_RUNTIME}.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check wrapper, runtime, and Codex host diagnostics")
    doctor.add_argument("--smoke-fixture", action="store_true", help="Run adapter-smoke against the vendored minimal fixture")
    doctor.set_defaults(func=cmd_doctor)

    contract = sub.add_parser(RUNTIME_CONTRACT, help="Emit the runtime contract through the wrapper")
    contract.set_defaults(func=cmd_runtime_contract)

    smoke = sub.add_parser(ADAPTER_SMOKE, help="Run runtime adapter-smoke through the wrapper")
    smoke.add_argument("--dir", type=Path, required=True, help="Discussion directory")
    smoke.add_argument("--host-step", type=Path, help="Optional host-step path")
    smoke.set_defaults(func=cmd_adapter_smoke)

    loop = sub.add_parser(VALIDATE_LOOP, help="Run runtime validate-loop through the wrapper")
    loop.add_argument("dir", type=Path, help="Discussion directory")
    loop.set_defaults(func=cmd_validate_loop)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    runtime_override: str | None = None
    index = 0
    while index < len(raw):
        item = raw[index]
        if item == "--runtime" and index + 1 < len(raw):
            runtime_override = raw[index + 1]
            index += 2
            continue
        if item.startswith("--runtime="):
            runtime_override = item.split("=", 1)[1]
            index += 1
            continue
        break

    if index < len(raw) and raw[index] in PRIMITIVE_COMMANDS:
        args = argparse.Namespace(
            runtime=runtime_override,
            runtime_command=raw[index],
            runtime_args=raw[index + 1 :],
        )
        return cmd_runtime_primitive(args)

    parser = build_parser()
    args, unknown = parser.parse_known_args(raw)
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WrapperError as exc:
        emit({"ok": False, "errors": [exc.as_error()], "attempts": []})
        raise SystemExit(1) from None
    except BrokenPipeError:
        raise SystemExit(1) from None
    except Exception as exc:
        emit(
            {
                "ok": False,
                "errors": [
                    {
                        "code": "wrapper_internal_error",
                        "message": str(exc),
                        "exceptionType": type(exc).__name__,
                    }
                ],
                "attempts": [],
            }
        )
        raise SystemExit(1) from None
