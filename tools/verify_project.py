#!/usr/bin/env python3
"""Verify the integrity of an installed Aegis project state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


STATE_SCHEMA_VERSION = 1
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="Bootstrapped project directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project.resolve()

    if not project.is_dir():
        return fail(f"Project directory does not exist: {project}")

    state_path = project / ".aegis" / "aegis-version.json"
    if not state_path.is_file():
        return fail(f"Aegis state file is missing: {state_path}")

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"Aegis state file is not valid JSON: {exc}")

    if not isinstance(state, dict):
        return fail("Aegis state file must contain a JSON object.")

    required = (
        "schema_version",
        "aegis_version",
        "source_repository",
        "source_commit",
        "preset",
        "integrations",
        "skills",
        "skill_checksums",
        "status",
    )
    missing = [key for key in required if key not in state]
    if missing:
        return fail("Aegis state is missing keys: " + ", ".join(missing))

    if state["schema_version"] != STATE_SCHEMA_VERSION:
        return fail(
            f"Unsupported Aegis state schema: {state['schema_version']!r}"
        )

    if not isinstance(state["source_repository"], str) or not state["source_repository"]:
        return fail("Aegis source_repository must be a non-empty string.")
    if not isinstance(state["aegis_version"], str) or not state["aegis_version"]:
        return fail("Aegis aegis_version must be a non-empty string.")
    if not isinstance(state["source_commit"], str) or not COMMIT_PATTERN.fullmatch(state["source_commit"]):
        return fail("Aegis source_commit must be a 40-character lowercase SHA.")
    if state["preset"] not in {"core", "product", "all"}:
        return fail(f"Unsupported Aegis preset: {state['preset']!r}")
    if state["status"] != "active":
        return fail(f"Unsupported Aegis state status: {state['status']!r}")

    integrations = state["integrations"]
    skills = state["skills"]
    checksums = state["skill_checksums"]

    if not isinstance(integrations, list) or not all(isinstance(name, str) for name in integrations):
        return fail("Aegis integrations must be a string list.")
    if integrations != sorted(set(integrations)):
        return fail("Aegis integrations must be a sorted unique list.")
    if not isinstance(skills, list) or not all(isinstance(name, str) for name in skills):
        return fail("Aegis skills must be a string list.")
    if skills != sorted(set(skills)):
        return fail("Aegis skills must be a sorted unique list.")
    if not isinstance(checksums, dict) or not all(isinstance(name, str) for name in checksums):
        return fail("Aegis skill_checksums must be an object keyed by skill name.")
    if set(checksums) != set(skills):
        return fail("Aegis skill_checksums must match the installed skills exactly.")

    skill_root = project / ".agents" / "skills"
    for name in skills:
        if not isinstance(name, str) or not SKILL_NAME_PATTERN.fullmatch(name):
            return fail(f"Invalid Aegis skill name in state: {name!r}")

        checksum = checksums[name]
        if not isinstance(checksum, str) or not SHA256_PATTERN.fullmatch(checksum):
            return fail(f"Invalid checksum for Aegis skill: {name}")

        path = skill_root / name / "SKILL.md"
        if not path.is_file():
            return fail(f"Installed Aegis skill is missing: {path}")

        actual = sha256_file(path)
        if actual != checksum:
            return fail(
                f"Aegis skill checksum mismatch for {name}: "
                f"expected {checksum}, got {actual}"
            )

    print(
        f"Aegis project verification passed: "
        f"{state['aegis_version']} @ {state['source_commit']} "
        f"({len(skills)} skills)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
