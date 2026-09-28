#!/usr/bin/env python3
"""Run a read-only, deterministic security review over an Aegis repository."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


HIGH = "high"
MEDIUM = "medium"
LOW = "low"
SEVERITIES = {HIGH, MEDIUM, LOW}

ACTION_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*([^\s@]+)@([^\s#]+)",
    re.MULTILINE,
)
PINNED_REF_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SECRET_PATTERNS = (
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)
PROTECTED_REF_VALUES = {"refs/heads/main", "refs/heads/develop"}
GITHUB_API_RE = re.compile(r"https://api\.github\.com\b")
API_VERSION_HEADER = "X-GitHub-Api-Version"
PERMISSIONS_RE = re.compile(r"^permissions:\s*$", re.MULTILINE)
WRITE_PERMISSION_RE = re.compile(
    r"^\s{2,}[A-Za-z0-9_-]+:\s*write\s*$",
    re.MULTILINE,
)
WRITE_ALL_RE = re.compile(r"\b(?:write-all|permissions:\s*write-all)\b")
PULL_REQUEST_TARGET_RE = re.compile(r"\bpull_request_target\s*:")
WORKFLOW_SUFFIXES = {".yml", ".yaml"}


class SecurityReviewError(RuntimeError):
    """Raised when a security review cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """One deterministic security-review observation."""

    rule_id: str
    severity: str
    path: str
    message: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class SecurityReviewResult:
    """Read-only security-review result."""

    root: str
    status: str
    findings: tuple[SecurityFinding, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding(
    findings: list[SecurityFinding],
    *,
    rule_id: str,
    severity: str,
    path: Path,
    root: Path,
    message: str,
    line: int | None = None,
) -> None:
    if severity not in SEVERITIES:
        raise SecurityReviewError(f"Unsupported security finding severity: {severity}")
    findings.append(
        SecurityFinding(
            rule_id=rule_id,
            severity=severity,
            path=path.relative_to(root).as_posix(),
            message=message,
            line=line,
        )
    )


def _iter_review_files(root: Path) -> Iterable[Path]:
    workflow_root = root / ".github" / "workflows"
    if workflow_root.is_dir():
        yield from sorted(
            path
            for path in workflow_root.rglob("*")
            if path.is_file() and path.suffix.lower() in WORKFLOW_SUFFIXES
        )

    tools_root = root / "tools"
    if tools_root.is_dir():
        yield from sorted(
            path
            for path in tools_root.rglob("*.py")
            if path.is_file()
        )

    config_root = root / "config"
    if config_root.is_dir():
        yield from sorted(
            path
            for path in config_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}
        )


def _review_workflow(path: Path, text: str, root: Path, findings: list[SecurityFinding]) -> None:
    if PULL_REQUEST_TARGET_RE.search(text):
        match = PULL_REQUEST_TARGET_RE.search(text)
        _finding(
            findings,
            rule_id="workflow.untrusted-trigger",
            severity=HIGH,
            path=path,
            root=root,
            message="pull_request_target is not permitted by the Aegis security boundary.",
            line=_line_number(text, match.start()),
        )

    if not PERMISSIONS_RE.search(text):
        _finding(
            findings,
            rule_id="workflow.permissions-explicit",
            severity=HIGH,
            path=path,
            root=root,
            message="Workflow must declare an explicit top-level permissions block.",
        )

    if WRITE_ALL_RE.search(text):
        match = WRITE_ALL_RE.search(text)
        _finding(
            findings,
            rule_id="workflow.permissions-broad",
            severity=HIGH,
            path=path,
            root=root,
            message="Workflow requests broad write permissions.",
            line=_line_number(text, match.start()),
        )
    elif WRITE_PERMISSION_RE.search(text):
        match = WRITE_PERMISSION_RE.search(text)
        _finding(
            findings,
            rule_id="workflow.permissions-write",
            severity=MEDIUM,
            path=path,
            root=root,
            message="Workflow requests a write permission; verify that the permission is strictly required.",
            line=_line_number(text, match.start()),
        )

    for match in ACTION_RE.finditer(text):
        action, ref = match.groups()
        if action.startswith("./"):
            continue
        if not PINNED_REF_RE.fullmatch(ref):
            _finding(
                findings,
                rule_id="workflow.unpinned-action",
                severity=HIGH,
                path=path,
                root=root,
                message=f"Third-party action {action!r} is not pinned to a full commit SHA.",
                line=_line_number(text, match.start()),
            )

    if GITHUB_API_RE.search(text) and API_VERSION_HEADER not in text:
        _finding(
            findings,
            rule_id="github.api-version",
            severity=HIGH,
            path=path,
            root=root,
            message="GitHub API usage must send the explicit API-version header.",
        )


def _review_python(path: Path, text: str, root: Path, findings: list[SecurityFinding]) -> None:
    if GITHUB_API_RE.search(text) and API_VERSION_HEADER not in text:
        _finding(
            findings,
            rule_id="github.api-version",
            severity=HIGH,
            path=path,
            root=root,
            message="GitHub API usage must send the explicit API-version header.",
        )

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        _finding(
            findings,
            rule_id="python.syntax",
            severity=HIGH,
            path=path,
            root=root,
            message="Python source cannot be parsed for security review.",
            line=exc.lineno,
        )
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        function_name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
        owner_name = node.func.value.id if (
            isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
        ) else ""

        if owner_name == "subprocess":
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant):
                    if keyword.value.value is True:
                        _finding(
                            findings,
                            rule_id="python.subprocess-shell",
                            severity=HIGH,
                            path=path,
                            root=root,
                            message="subprocess execution with shell=True crosses the command-injection boundary.",
                            line=node.lineno,
                        )

            constants = [
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            ]
            joined = " ".join(constants)
            if re.search(r"\bgit\s+push\s+(?:[^\\n]*--force|-f)\b", joined):
                _finding(
                    findings,
                    rule_id="git.force-push",
                    severity=HIGH,
                    path=path,
                    root=root,
                    message="Executable subprocess path contains a force-push command.",
                    line=node.lineno,
                )
            if re.search(r"\bgit\s+reset\s+--hard\b", joined):
                _finding(
                    findings,
                    rule_id="git.destructive-reset",
                    severity=HIGH,
                    path=path,
                    root=root,
                    message="Executable subprocess path contains git reset --hard.",
                    line=node.lineno,
                )

    for dictionary in ast.walk(tree):
        if not isinstance(dictionary, ast.Dict):
            continue
        for key, value in zip(dictionary.keys, dictionary.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "force"
                and isinstance(value, ast.Constant)
                and value.value is True
            ):
                _finding(
                    findings,
                    rule_id="git.force-update",
                    severity=HIGH,
                    path=path,
                    root=root,
                    message="Executable Git ref update requests force=True.",
                    line=dictionary.lineno,
                )

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and (
                (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"_request", "request"}
                )
                or (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"_request", "request"}
                )
            )
        ):
            continue

        method_constants = {
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant)
            and argument.value in {"POST", "PUT", "PATCH"}
        }
        path_constants = {
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
        }
        protected_paths = path_constants & PROTECTED_REF_VALUES
        if method_constants and protected_paths:
            _finding(
                findings,
                rule_id="git.protected-direct-write",
                severity=HIGH,
                path=path,
                root=root,
                message="Executable tooling directly writes to a hardcoded protected ref.",
                line=node.lineno,
            )


def _review_secrets(path: Path, text: str, root: Path, findings: list[SecurityFinding]) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            _finding(
                findings,
                rule_id="secrets.high-confidence",
                severity=HIGH,
                path=path,
                root=root,
                message="High-confidence credential material appears in a reviewed source/config file.",
                line=_line_number(text, match.start()),
            )
            break


def assess_repository(root: str | Path) -> SecurityReviewResult:
    """Run the read-only security review against one repository root."""
    project_root = Path(root).expanduser().resolve()
    if not project_root.is_dir():
        raise SecurityReviewError(f"Repository root does not exist: {project_root}")

    findings: list[SecurityFinding] = []
    files = list(_iter_review_files(project_root))
    if not files:
        _finding(
            findings,
            rule_id="repository.inventory",
            severity=HIGH,
            path=project_root / "README.md",
            root=project_root,
            message="Security review found no reviewable workflow or source files.",
        )
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SecurityReviewError(
                f"Unable to read security-review input: {path}"
            ) from exc

        if path.is_relative_to(project_root / ".github" / "workflows"):
            _review_workflow(path, text, project_root, findings)
        elif path.is_relative_to(project_root / "tools"):
            _review_python(path, text, project_root, findings)
        _review_secrets(path, text, project_root, findings)

    findings.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}[item.severity],
            item.path,
            item.line or 0,
            item.rule_id,
        )
    )
    status = "blocked" if any(item.severity == HIGH for item in findings) else "ready"
    return SecurityReviewResult(
        root=str(project_root),
        status=status,
        findings=tuple(findings),
    )


def _to_dict(result: SecurityReviewResult) -> dict[str, object]:
    return {
        "status": result.status,
        "root": result.root,
        "findings": [asdict(item) for item in result.findings],
        "summary": {
            "high": sum(item.severity == HIGH for item in result.findings),
            "medium": sum(item.severity == MEDIUM for item in result.findings),
            "low": sum(item.severity == LOW for item in result.findings),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Aegis security review.")
    parser.add_argument("root")
    args = parser.parse_args()

    try:
        result = assess_repository(args.root)
    except SecurityReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(result), indent=2, sort_keys=True))
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
