#!/usr/bin/env python3
"""Validate structural invariants of the Aegis repository."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^0\.\d+\.\d+-alpha\.\d+$")
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_skill(path: Path, seen_names: set[str]) -> None:
    text = path.read_text(encoding="utf-8")

    if not text.startswith("---\n"):
        fail(f"{path}: missing Agent Skills front matter.")

    front_matter = text.split("---\n", 2)
    if len(front_matter) < 3:
        fail(f"{path}: malformed front matter.")

    header = front_matter[1]
    name_match = re.search(r"^name:\s*(\S+)\s*$", header, re.MULTILINE)
    description_match = re.search(
        r"^description:\s*(.+)$", header, re.MULTILINE
    )

    if not name_match or not description_match:
        fail(f"{path}: name/description front matter is incomplete.")

    name = name_match.group(1)
    if not SKILL_NAME_PATTERN.fullmatch(name):
        fail(f"{path}: invalid skill name {name!r}.")

    if name in seen_names:
        fail(f"Duplicate skill name: {name}")
    seen_names.add(name)

    if re.search(r"[А-Яа-яЁё]", text):
        fail(f"{path}: canonical skills must be English; Cyrillic text found.")


def main() -> int:
    version_file = ROOT / "VERSION"
    manifest_file = ROOT / "aegis-manifest.json"
    registry_file = ROOT / "skills" / "registry.json"

    if not version_file.is_file():
        fail("VERSION file is missing.")
    if not manifest_file.is_file():
        fail("aegis-manifest.json is missing.")
    if not registry_file.is_file():
        fail("skills/registry.json is missing.")

    version = version_file.read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        fail(f"Unsupported experimental version format: {version!r}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        fail("VERSION and aegis-manifest.json disagree.")

    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    if registry.get("version") != version:
        fail("VERSION and skills/registry.json disagree.")

    required = [
        "AGENTS.md",
        "00-constitution/core-principles.md",
        "01-orchestrator/SKILL.md",
        "skills/product-discovery/SKILL.md",
        "skills/version-verification/SKILL.md",
        "skills/git-hygiene/SKILL.md",
        "skills/user-communication/SKILL.md",
        "skills/offline-operation/SKILL.md",
        "skills/skill-authoring/SKILL.md",
        "skills/knowledge-gap/SKILL.md",
        "skills/workflows/project-discovery/SKILL.md",
        "skills/workflows/feature-implementation/SKILL.md",
        "skills/workflows/bug-fix/SKILL.md",
        "skills/workflows/code-review/SKILL.md",
        "skills/workflows/aegis-update-validation/SKILL.md",
        "05-quality-gates/README.md",
        "06-git-github/branching-policy.md",
        "07-knowledge/knowledge-lifecycle.md",
        "08-offline/offline-architecture.md",
        "docs/architecture/overview.md",
        "docs/product/discovery-mode.md",
        "docs/product/user-decision-model.md",
        "templates/product-brief.md",
        "templates/product-decision-questionnaire.md",
        "templates/AGENTS.md",
        "tools/bootstrap_project.py",
        "skills/registry.json",
    ]

    missing = [path for path in required if not (ROOT / path).is_file()]
    if missing:
        fail("Missing required files: " + ", ".join(missing))

    seen_names: set[str] = set()
    for skill in sorted((ROOT / "skills").rglob("SKILL.md")):
        validate_skill(skill, seen_names)

    registry_names: set[str] = set()
    for entry in registry.get("skills", []):
        name = entry.get("name")
        path = entry.get("path")
        if not name or not path:
            fail("Every registry entry must contain name and path.")
        if name in registry_names:
            fail(f"Duplicate registry skill name: {name}")
        registry_names.add(name)
        if not (ROOT / path).is_file():
            fail(f"Registry path does not exist: {path}")

    missing_from_registry = seen_names - registry_names
    if missing_from_registry:
        fail("Skills missing from registry: " + ", ".join(sorted(missing_from_registry)))

    print(f"Aegis {version}: structural validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
