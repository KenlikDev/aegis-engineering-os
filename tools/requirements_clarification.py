#!/usr/bin/env python3
"""Identify missing work-item requirements without inventing user decisions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


PLACEHOLDER_RE = re.compile(
    r"^(?:\.\.\.|tbd|todo|to be decided|fill in|n/?a)\.?$",
    re.IGNORECASE,
)

class RequirementsClarificationError(RuntimeError):
    """Raised when requirements clarification cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    """One deterministic clarification question."""

    question_id: str
    severity: str
    section: str
    question: str
    evidence: str


@dataclass(frozen=True, slots=True)
class RequirementsReport:
    """Read-only requirements clarification result."""

    path: str
    status: str
    questions: tuple[ClarificationQuestion, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _is_placeholder(value: str) -> bool:
    normalized = _normalize(value).strip(" -*_:")
    return not normalized or bool(PLACEHOLDER_RE.fullmatch(normalized))


def _sections(markdown: str) -> dict[str, str]:
    heading_re = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(heading_re.finditer(markdown))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = _normalize(match.group(1)).lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        result[heading] = markdown[match.end():end].strip()
    return result


def _subsections(section_text: str) -> dict[str, str]:
    matches = list(
        re.finditer(r"^###\s+(.+?)\s*$", section_text, re.MULTILINE)
    )
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = _normalize(match.group(1)).lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        result[heading] = section_text[match.end():end].strip()
    return result


def _has_meaningful_lines(text: str) -> bool:
    for raw_line in text.splitlines():
        line = _normalize(raw_line)
        if not line or line.startswith("<!--"):
            continue
        if line.startswith("#"):
            continue
        if line.lower().startswith("what outcome is required?"):
            continue
        if line in {"- ...", "...", "- [ ] ...", "[ ] ..."}:
            continue
        if _is_placeholder(line):
            continue
        return True
    return False


def _question(
    questions: list[ClarificationQuestion],
    *,
    question_id: str,
    severity: str,
    section: str,
    question: str,
    evidence: str,
) -> None:
    questions.append(
        ClarificationQuestion(
            question_id=question_id,
            severity=severity,
            section=section,
            question=question,
            evidence=evidence,
        )
    )


def clarify_requirements(path: str | Path) -> RequirementsReport:
    """Read one work-item document and report unresolved requirements."""
    document = Path(path).expanduser().resolve()
    if not document.is_file():
        raise RequirementsClarificationError(f"Work-item document does not exist: {document}")

    try:
        markdown = document.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RequirementsClarificationError(
            f"Unable to read work-item document: {document}"
        ) from exc

    sections = _sections(markdown)
    questions: list[ClarificationQuestion] = []

    identity = sections.get("identity", "")
    title_line = next(
        (
            _normalize(line.split(":", 1)[1])
            for line in identity.splitlines()
            if ":" in line and line.split(":", 1)[0].strip().lower() == "title"
        ),
        "",
    )
    if _is_placeholder(title_line):
        _question(
            questions,
            question_id="identity.title",
            severity="blocker",
            section="Identity",
            question="What is the concrete work-item title?",
            evidence="Identity/Title is missing or still a placeholder.",
        )

    intent = sections.get("intent", "")
    if not _has_meaningful_lines(intent):
        _question(
            questions,
            question_id="intent.outcome",
            severity="blocker",
            section="Intent",
            question="What concrete outcome must this work item produce?",
            evidence="Intent does not contain a meaningful outcome statement.",
        )

    scope = sections.get("scope", "")
    scope_parts = _subsections(scope)
    in_scope = scope_parts.get("in scope", "")
    out_scope = scope_parts.get("out of scope", "")
    if not _has_meaningful_lines(in_scope):
        _question(
            questions,
            question_id="scope.in",
            severity="blocker",
            section="Scope / In scope",
            question="Which concrete work is included in this item?",
            evidence="Scope/In scope is missing or still a placeholder.",
        )
    if not _has_meaningful_lines(out_scope):
        _question(
            questions,
            question_id="scope.out",
            severity="blocker",
            section="Scope / Out of scope",
            question="Which work is explicitly excluded or deferred?",
            evidence="Scope/Out of scope is missing or still a placeholder.",
        )

    acceptance = sections.get("acceptance criteria", "")
    acceptance_items = [
        _normalize(line)
        for line in acceptance.splitlines()
        if re.match(r"^\s*-\s+\[[ xX]\]\s+", line)
    ]
    meaningful_acceptance = [
        item for item in acceptance_items if not _is_placeholder(re.sub(r"^\-\s+\[[ xX]\]\s+", "", item))
    ]
    if not meaningful_acceptance:
        _question(
            questions,
            question_id="acceptance.criteria",
            severity="blocker",
            section="Acceptance criteria",
            question="What observable criteria will prove that the requested outcome is complete?",
            evidence="No meaningful checklist acceptance criterion was found.",
        )

    verification = sections.get("verification plan", "")
    if not _has_meaningful_lines(verification):
        _question(
            questions,
            question_id="verification.plan",
            severity="blocker",
            section="Verification plan",
            question="How will the implementation be verified with observable evidence?",
            evidence="Verification plan is missing or still a placeholder.",
        )

    dependencies = sections.get("dependencies", "")
    if not _has_meaningful_lines(dependencies):
        _question(
            questions,
            question_id="dependencies.unknown",
            severity="warning",
            section="Dependencies",
            question="Are there dependencies, external systems, or prerequisites that must be recorded?",
            evidence="Dependencies contains no explicit information.",
        )

    risks = sections.get("risks", "")
    if not _has_meaningful_lines(risks):
        _question(
            questions,
            question_id="risks.unknown",
            severity="warning",
            section="Risks",
            question="What known risks or uncertainty should be recorded before implementation?",
            evidence="Risks contains no explicit information.",
        )

    status = "needs-clarification" if any(
        question.severity == "blocker" for question in questions
    ) else "ready"

    return RequirementsReport(
        path=document.as_posix(),
        status=status,
        questions=tuple(questions),
    )


def _to_dict(report: RequirementsReport) -> dict[str, object]:
    return {
        "status": report.status,
        "path": report.path,
        "ready": report.ready,
        "questions": [asdict(question) for question in report.questions],
        "summary": {
            "blockers": sum(q.severity == "blocker" for q in report.questions),
            "warnings": sum(q.severity == "warning" for q in report.questions),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check work-item completeness without inventing requirements."
    )
    parser.add_argument("work_item")
    args = parser.parse_args()

    try:
        report = clarify_requirements(args.work_item)
    except RequirementsClarificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_to_dict(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
