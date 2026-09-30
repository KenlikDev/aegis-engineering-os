#!/usr/bin/env python3
"""Run a read-only, deterministic security review over an Aegis repository."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
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
    review_roots = (
        (root / ".github" / "workflows", WORKFLOW_SUFFIXES),
        (root / "tools", {".py"}),
        (root / "config", {".json", ".yaml", ".yml"}),
    )

    for review_root, suffixes in review_roots:
        if review_root.is_symlink():
            raise SecurityReviewError(
                f"Security review scope must not be a symbolic link: {review_root}"
            )
        if not review_root.is_dir():
            continue

        for path in sorted(review_root.rglob("*")):
            if path.is_symlink():
                raise SecurityReviewError(
                    f"Security review input must not be a symbolic link: {path}"
                )
            if path.is_file() and path.suffix.lower() in suffixes:
                yield path



def _strip_yaml_comments(text: str) -> str:
    """Remove YAML comments without treating quoted '#' characters as comments."""
    cleaned_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        single_quoted = False
        double_quoted = False
        escaped = False
        cut_at: int | None = None
        index = 0

        while index < len(line):
            character = line[index]
            if double_quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    double_quoted = False
            elif single_quoted:
                if character == "'":
                    if index + 1 < len(line) and line[index + 1] == "'":
                        index += 1
                    else:
                        single_quoted = False
            elif character == "'":
                single_quoted = True
            elif character == '"':
                double_quoted = True
            elif character == "#" and (index == 0 or line[index - 1].isspace()):
                cut_at = index
                break
            index += 1

        if cut_at is None:
            cleaned_lines.append(line)
        else:
            newline = "\n" if line.endswith("\n") else ""
            cleaned_lines.append(line[:cut_at] + newline)

    return "".join(cleaned_lines)

def _extract_workflow_run_blocks(text: str) -> list[str]:
    """Extract executable GitHub Actions run scalars without interpreting other YAML fields."""
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        match = re.match(r"^(?P<indent>\s*)(?:-\s+)?run:\s*(?P<value>.*)$", line)
        if match is None:
            index += 1
            continue

        indent = len(match.group("indent"))
        value = match.group("value")
        block_lines = [value]
        if value in {"|", "|-", "|+", ">", ">-", ">+"}:
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                    break
                block_lines.append(candidate)
                index += 1
        blocks.append("\n".join(block_lines))
        index += 1

    return blocks


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

    workflow_text = _strip_yaml_comments(text)
    run_blocks = _extract_workflow_run_blocks(workflow_text)
    for run_block in run_blocks:
        if GITHUB_API_RE.search(run_block) and API_VERSION_HEADER not in run_block:
            _finding(
                findings,
                rule_id="github.api-version",
                severity=HIGH,
                path=path,
                root=root,
                message="GitHub API usage in an executable run block must send the explicit API-version header.",
            )

    if not run_blocks and GITHUB_API_RE.search(workflow_text) and API_VERSION_HEADER not in workflow_text:
        _finding(
            findings,
            rule_id="github.api-version",
            severity=HIGH,
            path=path,
            root=root,
            message="GitHub API usage must send the explicit API-version header.",
        )



def _review_python(path: Path, text: str, root: Path, findings: list[SecurityFinding]) -> None:
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

    def contains_api_version_header(expression: ast.AST | None) -> bool:
        if expression is None:
            return False
        for child in ast.walk(expression):
            if isinstance(child, ast.Call) and (
                (
                    isinstance(child.func, ast.Name)
                    and child.func.id == "github_api_headers"
                )
                or (
                    isinstance(child.func, ast.Attribute)
                    and child.func.attr == "github_api_headers"
                )
            ):
                return True
            if isinstance(child, ast.Dict):
                if any(
                    isinstance(key, ast.Constant)
                    and key.value == API_VERSION_HEADER
                    for key in child.keys
                ):
                    return True
        return False

    header_assignments: dict[str, list[tuple[int, bool]]] = {}
    for node in sorted(
        (candidate for candidate in ast.walk(tree) if isinstance(candidate, ast.Assign)),
        key=lambda candidate: candidate.lineno,
    ):
        compliant = contains_api_version_header(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                header_assignments.setdefault(target.id, []).append(
                    (node.lineno, compliant)
                )

    def request_headers_are_compliant(expression: ast.AST | None, line: int) -> bool:
        if expression is None:
            return False
        for child in ast.walk(expression):
            if isinstance(child, ast.Name):
                assignments = [
                    compliant
                    for assignment_line, compliant in header_assignments.get(child.id, [])
                    if assignment_line < line
                ]
                if assignments and all(assignments):
                    return True
            if contains_api_version_header(child):
                return True
        return False

    def expression_contains_github_url(
        expression: ast.AST | None,
        github_url_names: set[str],
    ) -> bool:
        if expression is None:
            return False
        for child in ast.walk(expression):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if GITHUB_API_RE.search(child.value):
                    return True
            if isinstance(child, ast.Name) and child.id in github_url_names:
                return True
        return False

    github_url_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not expression_contains_github_url(node.value, github_url_names):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in github_url_names:
                    github_url_names.add(target.id)
                    changed = True

    request_sinks: list[tuple[ast.Call, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_request = (
            (isinstance(node.func, ast.Name) and node.func.id == "Request")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "Request")
        )
        if not is_request:
            continue
        url_expression = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "url"),
            None,
        )
        request_sinks.append(
            (
                node,
                expression_contains_github_url(url_expression, github_url_names),
            )
        )

    relative_path = path.relative_to(root).as_posix()
    is_shared_header_policy_module = relative_path == "tools/github_http_security.py"
    if GITHUB_API_RE.search(text) and not is_shared_header_policy_module:
        github_request_sinks = [
            (node, request_headers_are_compliant(
                next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "headers"),
                    None,
                ),
                node.lineno,
            ))
            for node, is_github in request_sinks
            if is_github
        ]

        for node, compliant in github_request_sinks:
            if not compliant:
                _finding(
                    findings,
                    rule_id="github.api-version",
                    severity=HIGH,
                    path=path,
                    root=root,
                    message="GitHub API request must send the explicit API-version header.",
                    line=node.lineno,
                )

        if not github_request_sinks and not any(
            request_headers_are_compliant(
                next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "headers"),
                    None,
                ),
                node.lineno,
            )
            for node, _ in request_sinks
        ):
            _finding(
                findings,
                rule_id="github.api-version",
                severity=HIGH,
                path=path,
                root=root,
                message="GitHub API usage must send the explicit API-version header.",
            )

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
    parser.add_argument(
        "--canonical-evidence-output",
        type=Path,
        help="Optional canonical evidence-provenance output path.",
    )
    parser.add_argument(
        "--revision",
        help="Optional exact repository revision associated with this review.",
    )
    args = parser.parse_args()

    try:
        observed_at = datetime.now(timezone.utc)
        result = assess_repository(args.root)
        if args.canonical_evidence_output is not None:
            from evidence_adapters import security_review_evidence
            from evidence_contract import write_evidence

            write_evidence(
                security_review_evidence(
                    result,
                    observed_at=observed_at,
                    revision=args.revision,
                ),
                args.canonical_evidence_output,
            )
    except (SecurityReviewError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(result), indent=2, sort_keys=True))
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
