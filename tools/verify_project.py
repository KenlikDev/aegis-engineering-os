#!/usr/bin/env python3
"""Verify the integrity of an installed Aegis project state."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from pathlib import Path

from evidence_contract import EvidenceContractError, parse_json_object


STATE_SCHEMA_VERSION = 2
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def _open_regular_file_no_follow(path: Path) -> int:
    """Open one regular file through no-follow directory file descriptors."""
    if (
        os.name != "posix"
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
    ):
        raise OSError(
            "Secure verifier reads require POSIX directory-FD and no-follow support."
        )

    absolute = Path(os.path.abspath(path))
    if absolute == Path(absolute.anchor):
        raise OSError(f"Verifier input must identify a file path: {path}")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parent.parts:
            if component == absolute.anchor:
                continue
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd

        file_fd = os.open(
            absolute.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise OSError(f"Verifier input must be a regular file: {path}")
            return file_fd
        except Exception:
            os.close(file_fd)
            raise
    finally:
        os.close(directory_fd)


def _read_regular_file_no_follow(
    path: Path,
    *,
    max_bytes: int | None = None,
) -> bytes:
    """Read one regular file through an anchored no-follow descriptor."""
    if max_bytes is not None and (not isinstance(max_bytes, int) or max_bytes <= 0):
        raise ValueError("Maximum verifier input size must be positive.")

    file_fd = _open_regular_file_no_follow(path)
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise OSError(
                    f"Verifier input exceeds the {max_bytes}-byte limit: {path}"
                )
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(file_fd)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    file_fd = _open_regular_file_no_follow(path)
    try:
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(file_fd)
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

    aegis_root = project / ".aegis"
    if aegis_root.is_symlink():
        return fail("Aegis .aegis root must not be a symbolic link.")
    if not aegis_root.is_dir():
        return fail(f"Aegis state directory is missing: {aegis_root}")

    state_path = aegis_root / "aegis-version.json"
    if state_path.is_symlink():
        return fail("Aegis state file must not be a symbolic link.")
    if not state_path.is_file():
        return fail(f"Aegis state file is missing: {state_path}")

    try:
        state = parse_json_object(
            _read_regular_file_no_follow(state_path, max_bytes=65536),
            label="Aegis state JSON",
        )
    except (EvidenceContractError, OSError, UnicodeDecodeError, ValueError) as exc:
        return fail(f"Aegis state file is not valid strict JSON: {exc}")

    required = (
        "schema_version",
        "aegis_version",
        "source_repository",
        "source_commit",
        "source_worktree_clean",
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

    agents_managed = state.get("agents_managed", False)
    agents_sha256 = state.get("agents_sha256")
    if not isinstance(agents_managed, bool):
        return fail("Aegis agents_managed must be boolean.")
    if agents_managed:
        if not isinstance(agents_sha256, str) or not SHA256_PATTERN.fullmatch(agents_sha256):
            return fail("Managed AGENTS.md requires a lowercase SHA-256 agents_sha256.")
    elif agents_sha256 is not None:
        return fail("Unmanaged AGENTS.md state must not contain agents_sha256.")

    if not isinstance(state["source_repository"], str) or not state["source_repository"]:
        return fail("Aegis source_repository must be a non-empty string.")
    if not isinstance(state["aegis_version"], str) or not state["aegis_version"]:
        return fail("Aegis aegis_version must be a non-empty string.")
    if not isinstance(state["source_commit"], str) or not COMMIT_PATTERN.fullmatch(
        state["source_commit"]
    ):
        return fail("Aegis source_commit must be a 40-character lowercase SHA.")
    if state["source_worktree_clean"] is not True:
        return fail("Aegis source_worktree_clean must be true.")
    if state["preset"] not in {"core", "product", "all"}:
        return fail(f"Unsupported Aegis preset: {state['preset']!r}")
    if state["status"] != "active":
        return fail(f"Unsupported Aegis state status: {state['status']!r}")

    integrations = state["integrations"]
    skills = state["skills"]
    checksums = state["skill_checksums"]

    if not isinstance(integrations, list) or not all(
        isinstance(name, str) for name in integrations
    ):
        return fail("Aegis integrations must be a string list.")
    if integrations != sorted(set(integrations)):
        return fail("Aegis integrations must be a sorted unique list.")
    if not isinstance(skills, list) or not all(
        isinstance(name, str) for name in skills
    ):
        return fail("Aegis skills must be a string list.")
    if skills != sorted(set(skills)):
        return fail("Aegis skills must be a sorted unique list.")
    if not isinstance(checksums, dict) or not all(
        isinstance(name, str) for name in checksums
    ):
        return fail("Aegis skill_checksums must be an object keyed by skill name.")
    if set(checksums) != set(skills):
        return fail("Aegis skill_checksums must match the installed skills exactly.")

    agents_root = project / ".agents"
    if agents_root.is_symlink():
        return fail("Aegis .agents root must not be a symbolic link.")
    if not agents_root.is_dir():
        return fail(f"Aegis agent skills root is missing: {agents_root}")

    skill_root = agents_root / "skills"
    if skill_root.is_symlink():
        return fail("Aegis .agents/skills root must not be a symbolic link.")
    if not skill_root.is_dir():
        return fail(f"Aegis skill root is missing: {skill_root}")

    for name in skills:
        if not SKILL_NAME_PATTERN.fullmatch(name):
            return fail(f"Invalid Aegis skill name in state: {name!r}")

        checksum = checksums[name]
        if not isinstance(checksum, str) or not SHA256_PATTERN.fullmatch(checksum):
            return fail(f"Invalid checksum for Aegis skill: {name}")

        skill_directory = skill_root / name
        if skill_directory.is_symlink():
            return fail(
                f"Installed Aegis skill directory must not be a symbolic link: {skill_directory}"
            )
        if not skill_directory.is_dir():
            return fail(f"Installed Aegis skill directory is missing: {skill_directory}")

        path = skill_directory / "SKILL.md"
        if path.is_symlink():
            return fail(
                f"Installed Aegis skill file must not be a symbolic link: {path}"
            )
        if not path.is_file():
            return fail(f"Installed Aegis skill is missing: {path}")

        actual = sha256_file(path)
        if actual != checksum:
            return fail(
                f"Aegis skill checksum mismatch for {name}: "
                f"expected {checksum}, got {actual}"
            )

    if agents_managed:
        agents_path = project / "AGENTS.md"
        if agents_path.is_symlink():
            return fail("Managed AGENTS.md must not be a symbolic link.")
        if not agents_path.is_file():
            return fail(f"Managed AGENTS.md is missing: {agents_path}")
        actual_agents_sha256 = sha256_file(agents_path)
        if actual_agents_sha256 != agents_sha256:
            return fail(
                "Managed AGENTS.md checksum mismatch: "
                f"expected {agents_sha256}, got {actual_agents_sha256}"
            )

    print(
        f"Aegis project verification passed: "
        f"{state['aegis_version']} @ {state['source_commit']} "
        f"({len(skills)} skills)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
