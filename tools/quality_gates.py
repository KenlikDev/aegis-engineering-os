#!/usr/bin/env python3
"""Validate and execute explicitly declared project quality gates."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from work_item_lifecycle import (
    GitHubIssuesProvider,
    LifecycleState,
    Traceability,
    WorkItemLifecycleError,
    WorkItemProvider,
    require_verified_mutation,
)

SCHEMA_VERSION = 1
DEFAULT_MANIFEST = Path(".aegis") / "quality-gates.json"
DEFAULT_GATE_TIMEOUT_SECONDS = 600.0
MAX_GATE_TIMEOUT_SECONDS = 86400.0
MAX_OUTPUT_CHARS = 32768
GATE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SENSITIVE_ENV_KEY_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE_KEY|API_KEY|ACCESS_KEY|CREDENTIAL)",
    re.IGNORECASE,
)
SENSITIVE_OUTPUT_RE = re.compile(
    r"(?i)((?:bearer|token)\s+)[^\s,;]+|"
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\s*[:=]\s*)[^\s,;]+"
)


class QualityGateError(RuntimeError):
    """Raised when a project quality-gate run cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class QualityGate:
    """Validated executable project quality gate."""

    id: str
    description: str
    command: tuple[str, ...]
    working_directory: str
    timeout_seconds: float
    required: bool
    environment: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    """Observed result of one quality gate."""

    id: str
    required: bool
    status: str
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class QualityGateRunEvidence:
    """Aggregate evidence for one quality-gate execution."""

    status: str
    project: str
    manifest: str
    gates: tuple[QualityGateResult, ...]
    required_failures: tuple[str, ...]


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityGateError(f"Unable to read quality-gate manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualityGateError("Quality-gate manifest must contain a JSON object.")
    return value


def _validate_command(command: object, gate_id: str) -> tuple[str, ...]:
    if not isinstance(command, list) or not command:
        raise QualityGateError(f"Gate {gate_id!r} command must be a non-empty argv list.")
    if len(command) > 64:
        raise QualityGateError(f"Gate {gate_id!r} command has too many arguments.")
    values: list[str] = []
    for index, item in enumerate(command):
        if not isinstance(item, str) or not item.strip():
            raise QualityGateError(
                f"Gate {gate_id!r} command argument {index} must be a non-empty string."
            )
        if "\x00" in item or "\r" in item or "\n" in item:
            raise QualityGateError(
                f"Gate {gate_id!r} command argument {index} contains forbidden control characters."
            )
        if len(item) > 4096:
            raise QualityGateError(
                f"Gate {gate_id!r} command argument {index} is too long."
            )
        values.append(item)
    return tuple(values)


def _validate_working_directory(value: object, gate_id: str) -> str:
    if value is None:
        return "."
    if not isinstance(value, str) or not value.strip():
        raise QualityGateError(f"Gate {gate_id!r} working_directory must be a relative path.")
    if "\x00" in value or value != value.strip():
        raise QualityGateError(
            f"Gate {gate_id!r} working_directory contains invalid whitespace or NUL."
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise QualityGateError(
            f"Gate {gate_id!r} working_directory must stay inside the project root."
        )
    return value or "."


def _validate_environment(value: object, gate_id: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise QualityGateError(f"Gate {gate_id!r} environment must be an object.")
    result: dict[str, str] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str) or not ENV_KEY_RE.fullmatch(key):
            raise QualityGateError(
                f"Gate {gate_id!r} contains an invalid environment variable name."
            )
        if SENSITIVE_ENV_KEY_RE.search(key):
            raise QualityGateError(
                f"Gate {gate_id!r} must not declare secret-like environment variables."
            )
        if not isinstance(raw_value, str) or "\x00" in raw_value or "\r" in raw_value or "\n" in raw_value:
            raise QualityGateError(
                f"Gate {gate_id!r} environment values must be single-line strings."
            )
        result[key] = raw_value
    return result


def load_quality_gates(path: Path) -> tuple[QualityGate, ...]:
    """Load, validate, and preserve manifest gate order."""
    manifest = _load_json(path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise QualityGateError(
            f"Unsupported quality-gate schema version: {manifest.get('schema_version')!r}."
        )
    gates = manifest.get("gates")
    if not isinstance(gates, list) or not gates:
        raise QualityGateError("Quality-gate manifest must declare at least one gate.")

    seen: set[str] = set()
    parsed: list[QualityGate] = []
    required_count = 0
    for raw_gate in gates:
        if not isinstance(raw_gate, dict):
            raise QualityGateError("Every quality gate must be an object.")
        gate_id = raw_gate.get("id")
        if not isinstance(gate_id, str) or not GATE_ID_RE.fullmatch(gate_id):
            raise QualityGateError(f"Invalid quality-gate id: {gate_id!r}.")
        if gate_id in seen:
            raise QualityGateError(f"Duplicate quality-gate id: {gate_id!r}.")
        seen.add(gate_id)

        description = raw_gate.get("description", "")
        if not isinstance(description, str):
            raise QualityGateError(f"Gate {gate_id!r} description must be a string.")

        command = _validate_command(raw_gate.get("command"), gate_id)
        working_directory = _validate_working_directory(
            raw_gate.get("working_directory"),
            gate_id,
        )

        timeout = raw_gate.get("timeout_seconds", DEFAULT_GATE_TIMEOUT_SECONDS)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise QualityGateError(f"Gate {gate_id!r} timeout_seconds must be numeric.")
        if not 0 < float(timeout) <= MAX_GATE_TIMEOUT_SECONDS:
            raise QualityGateError(
                f"Gate {gate_id!r} timeout_seconds must be between 0 and "
                f"{MAX_GATE_TIMEOUT_SECONDS} seconds."
            )

        required = raw_gate.get("required", True)
        if not isinstance(required, bool):
            raise QualityGateError(f"Gate {gate_id!r} required must be boolean.")

        environment = _validate_environment(raw_gate.get("environment"), gate_id)
        if required:
            required_count += 1

        parsed.append(
            QualityGate(
                id=gate_id,
                description=description,
                command=command,
                working_directory=working_directory,
                timeout_seconds=float(timeout),
                required=required,
                environment=environment,
            )
        )
    if required_count == 0:
        raise QualityGateError("Quality-gate manifest must declare at least one required gate.")
    return tuple(parsed)


def _redact_output(value: str, secret_values: tuple[str, ...] = ()) -> str:
    """Redact configured secret values and common credential-like output forms."""
    redacted = value
    for secret in secret_values:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = SENSITIVE_OUTPUT_RE.sub(
        lambda match: f"{match.group(1) or match.group(2)}[REDACTED]",
        redacted,
    )
    if len(redacted) > MAX_OUTPUT_CHARS:
        return redacted[:MAX_OUTPUT_CHARS] + "\n[OUTPUT_TRUNCATED]\n"
    return redacted


def _secret_values_from_environment(environment: Mapping[str, str]) -> tuple[str, ...]:
    values = [
        value
        for key, value in environment.items()
        if SENSITIVE_ENV_KEY_RE.search(key) and len(value) >= 4
    ]
    return tuple(sorted(set(values), key=len, reverse=True))


def _gate_environment(gate: QualityGate) -> tuple[dict[str, str], tuple[str, ...]]:
    environment = os.environ.copy()
    environment.update(gate.environment)
    return environment, _secret_values_from_environment(environment)


def run_gate(
    project: Path,
    gate: QualityGate,
    *,
    run_command: CommandRunner = subprocess.run,
) -> QualityGateResult:
    """Run one declared gate directly, without a shell."""
    working_directory = (project / gate.working_directory).resolve()
    if not working_directory.is_dir() or (
        working_directory != project
        and project not in working_directory.parents
    ):
        raise QualityGateError(
            f"Gate {gate.id!r} working directory escaped project root: {working_directory}"
        )

    environment, secret_values = _gate_environment(gate)
    started = time.monotonic()
    try:
        result = run_command(
            list(gate.command),
            cwd=working_directory,
            env=environment,
            check=False,
            text=True,
            capture_output=True,
            timeout=gate.timeout_seconds,
        )
        duration = time.monotonic() - started
        return QualityGateResult(
            id=gate.id,
            required=gate.required,
            status="passed" if result.returncode == 0 else "failed",
            exit_code=result.returncode,
            timed_out=False,
            duration_seconds=round(duration, 3),
            stdout=_redact_output(result.stdout or "", secret_values),
            stderr=_redact_output(result.stderr or "", secret_values),
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return QualityGateResult(
            id=gate.id,
            required=gate.required,
            status="timed_out",
            exit_code=None,
            timed_out=True,
            duration_seconds=round(duration, 3),
            stdout=_redact_output(stdout, secret_values),
            stderr=_redact_output(stderr, secret_values),
        )
    except FileNotFoundError as exc:
        duration = time.monotonic() - started
        return QualityGateResult(
            id=gate.id,
            required=gate.required,
            status="failed",
            exit_code=None,
            timed_out=False,
            duration_seconds=round(duration, 3),
            stdout="",
            stderr=_redact_output(f"Required executable was not found: {exc}", secret_values),
        )
    except OSError as exc:
        duration = time.monotonic() - started
        return QualityGateResult(
            id=gate.id,
            required=gate.required,
            status="failed",
            exit_code=None,
            timed_out=False,
            duration_seconds=round(duration, 3),
            stdout="",
            stderr=_redact_output(f"Unable to execute gate: {exc}", secret_values),
        )


def execute_quality_gates(
    project: Path,
    manifest_path: Path,
    *,
    run_command: CommandRunner = subprocess.run,
) -> QualityGateRunEvidence:
    """Execute all declared gates in manifest order."""
    root = project.expanduser().resolve()
    if not root.is_dir():
        raise QualityGateError(f"Project directory does not exist: {root}")
    manifest = manifest_path.expanduser().resolve()
    gates = load_quality_gates(manifest)
    try:
        manifest.relative_to(root)
    except ValueError as exc:
        raise QualityGateError("Quality-gate manifest must live inside the project.") from exc

    results: list[QualityGateResult] = []
    required_failures: list[str] = []
    for gate in gates:
        result = run_gate(root, gate, run_command=run_command)
        results.append(result)
        if gate.required and result.status != "passed":
            required_failures.append(gate.id)

    status = "verified" if not required_failures else "failed"
    return QualityGateRunEvidence(
        status=status,
        project=str(root),
        manifest=str(manifest),
        gates=tuple(results),
        required_failures=tuple(required_failures),
    )


def _evidence_dict(evidence: QualityGateRunEvidence) -> dict[str, Any]:
    return {
        "status": evidence.status,
        "project": evidence.project,
        "manifest": evidence.manifest,
        "required_failures": list(evidence.required_failures),
        "gates": [
            {
                "id": result.id,
                "required": result.required,
                "status": result.status,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "duration_seconds": result.duration_seconds,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in evidence.gates
        ],
    }


def _evidence_ref(path: Path) -> str:
    return path.name


def _sync_failure(
    provider: WorkItemProvider,
    work_item_id: str,
    evidence_ref: str | None,
    failed_gate_ids: tuple[str, ...],
) -> None:
    try:
        require_verified_mutation(
            provider.transition(
                work_item_id,
                LifecycleState.BLOCKED,
                expected_state=LifecycleState.VERIFICATION,
            ),
            "Quality-gate verification -> blocked transition",
        )
        details = [
            "<!-- aegis:quality-gate-failure:v1 -->",
            "## Aegis quality verification blocked",
            f"- **Work item:** {work_item_id}",
            f"- **Failed required gates:** {', '.join(failed_gate_ids)}",
        ]
        if evidence_ref:
            details.append(f"- **Evidence:** {evidence_ref}")
        require_verified_mutation(
            provider.comment(work_item_id, "\n".join(details)),
            "Quality-gate blocked-state comment",
        )
    except WorkItemLifecycleError as exc:
        raise QualityGateError(
            f"Quality verification failed and work-item synchronization also failed: {exc}"
        ) from exc


def _sync_success(
    provider: WorkItemProvider,
    work_item_id: str,
    evidence_ref: str | None,
) -> None:
    try:
        if evidence_ref:
            require_verified_mutation(
                provider.attach_traceability(
                    work_item_id,
                    Traceability(evidence_ref=evidence_ref),
                ),
                "Quality-gate traceability mutation",
            )
        require_verified_mutation(
            provider.comment(
                work_item_id,
                (
                    "<!-- aegis:quality-gate-success:v1 -->\n"
                    "## Aegis quality verification passed\n"
                    f"- **Work item:** {work_item_id}\n"
                    f"- **Evidence:** {evidence_ref or '(returned in execution output)'}"
                ),
            ),
            "Quality-gate success comment",
        )
        require_verified_mutation(
            provider.transition(
                work_item_id,
                LifecycleState.REVIEW,
                expected_state=LifecycleState.VERIFICATION,
            ),
            "Quality-gate verification -> review transition",
        )
    except WorkItemLifecycleError as exc:
        raise QualityGateError(
            f"Quality verification passed locally but work-item synchronization failed: {exc}"
        ) from exc

def run_with_optional_work_item(
    project: Path,
    manifest_path: Path,
    *,
    work_item_provider: WorkItemProvider | None = None,
    work_item_id: str | None = None,
    evidence_path: Path | None = None,
    run_command: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    """Run gates, optionally synchronize a work item, and return structured evidence."""
    if work_item_provider is not None:
        if not work_item_id:
            raise QualityGateError(
                "work_item_id is required when work-item synchronization is enabled."
            )
        item = work_item_provider.get(work_item_id)
        if item.state != LifecycleState.VERIFICATION:
            raise QualityGateError(
                "Quality verification requires a work item in verification state; "
                f"got {item.state.value}."
            )

    evidence = execute_quality_gates(
        project,
        manifest_path,
        run_command=run_command,
    )
    output = _evidence_dict(evidence)

    if evidence_path is not None:
        destination = evidence_path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence_reference = _evidence_ref(destination)
    else:
        evidence_reference = None

    if work_item_provider is not None:
        assert work_item_id is not None
        if evidence.required_failures:
            _sync_failure(
                work_item_provider,
                work_item_id,
                evidence_reference,
                evidence.required_failures,
            )
            output["work_item"] = {
                "provider": work_item_provider.get(work_item_id).provider,
                "state_after_execution": LifecycleState.BLOCKED.value,
                "verified": True,
            }
        else:
            _sync_success(
                work_item_provider,
                work_item_id,
                evidence_reference,
            )
            output["work_item"] = {
                "provider": work_item_provider.get(work_item_id).provider,
                "state_after_execution": LifecycleState.REVIEW.value,
                "verified": True,
            }

    return output


def build_provider(repository: str | None, token_env: str) -> GitHubIssuesProvider | None:
    if repository is None:
        return None
    token = os.environ.get(token_env, "")
    return GitHubIssuesProvider(repository, token)


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute explicitly declared project quality gates.")
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Project-local quality-gate manifest (default: .aegis/quality-gates.json).",
    )
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument("--work-item-id")
    parser.add_argument("--work-item-repository")
    parser.add_argument("--work-item-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        project = args.project.expanduser().resolve()
        manifest = args.manifest
        if not manifest.is_absolute():
            manifest = project / manifest
        gates = load_quality_gates(manifest)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "status": "validated",
                        "manifest": str(manifest.resolve()),
                        "gates": [
                            {
                                "id": gate.id,
                                "required": gate.required,
                                "command": list(gate.command),
                                "working_directory": gate.working_directory,
                                "timeout_seconds": gate.timeout_seconds,
                            }
                            for gate in gates
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        provider = build_provider(
            args.work_item_repository,
            args.work_item_token_env,
        )
        evidence = run_with_optional_work_item(
            project,
            manifest,
            work_item_provider=provider,
            work_item_id=args.work_item_id,
            evidence_path=args.evidence_path,
        )
    except (QualityGateError, WorkItemLifecycleError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
