#!/usr/bin/env python3
"""Install a controlled Aegis skill set into a target repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from evidence_contract import (
    EvidenceContractError,
    copy_file_atomically,
    load_json_object,
    write_json_atomically,
)


STATE_SCHEMA_VERSION = 2
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


SKILL_SOURCES = {
    "aegis-orchestrator": Path("01-orchestrator/SKILL.md"),
    "version-verification": Path("skills/version-verification/SKILL.md"),
    "git-hygiene": Path("skills/git-hygiene/SKILL.md"),
    "user-communication": Path("skills/user-communication/SKILL.md"),
    "offline-operation": Path("skills/offline-operation/SKILL.md"),
    "product-discovery": Path("skills/product-discovery/SKILL.md"),
    "skill-authoring": Path("skills/skill-authoring/SKILL.md"),
    "knowledge-gap": Path("skills/knowledge-gap/SKILL.md"),
    "state-verification": Path("skills/state-verification/SKILL.md"),
    "work-item-lifecycle": Path("skills/workflows/work-item-lifecycle/SKILL.md"),
    "github-issues": Path("skills/integrations/github-issues/SKILL.md"),
    "project-discovery": Path("skills/workflows/project-discovery/SKILL.md"),
    "feature-implementation": Path("skills/workflows/feature-implementation/SKILL.md"),
    "bug-fix": Path("skills/workflows/bug-fix/SKILL.md"),
    "code-review": Path("skills/workflows/code-review/SKILL.md"),
    "aegis-update-validation": Path("skills/workflows/aegis-update-validation/SKILL.md"),
}

ROLE_SKILLS = {
    "product-manager": Path("skills/roles/product-manager/SKILL.md"),
    "software-architect": Path("skills/roles/software-architect/SKILL.md"),
    "software-engineer": Path("skills/roles/software-engineer/SKILL.md"),
    "qa-engineer": Path("skills/roles/qa-engineer/SKILL.md"),
    "security-engineer": Path("skills/roles/security-engineer/SKILL.md"),
    "code-reviewer": Path("skills/roles/code-reviewer/SKILL.md"),
    "devops-engineer": Path("skills/roles/devops-engineer/SKILL.md"),
}

OPTIONAL_INTEGRATIONS = {
    "jira": Path("skills/integrations/jira/SKILL.md"),
    "confluence": Path("skills/integrations/confluence/SKILL.md"),
}

CORE_NAMES = (
    "aegis-orchestrator",
    "version-verification",
    "git-hygiene",
    "user-communication",
    "offline-operation",
    "skill-authoring",
    "knowledge-gap",
    "state-verification",
    "work-item-lifecycle",
    "github-issues",
    "project-discovery",
    "feature-implementation",
    "bug-fix",
    "code-review",
    "aegis-update-validation",
)

PRODUCT_NAMES = (
    "product-discovery",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, help="Target project directory")
    parser.add_argument(
        "--preset",
        choices=("core", "product", "all"),
        default="core",
    )
    parser.add_argument(
        "--integration",
        action="append",
        choices=tuple(OPTIONAL_INTEGRATIONS),
        default=[],
        help="Optional external integration to install; repeat for multiple integrations.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_sources(preset: str, integrations: list[str]) -> dict[str, Path]:
    names = list(CORE_NAMES)
    if preset in ("product", "all"):
        names.extend(PRODUCT_NAMES)
    selected = {
        name: SKILL_SOURCES[name]
        for name in names
        if name in SKILL_SOURCES
    }

    if preset == "all":
        selected.update(ROLE_SKILLS)
        selected.update(OPTIONAL_INTEGRATIONS)

    for integration in integrations:
        selected[integration] = OPTIONAL_INTEGRATIONS[integration]

    return selected


def ensure_project_outside_source(root: Path, project: Path) -> None:
    try:
        project.relative_to(root)
    except ValueError:
        return

    raise SystemExit(
        "Refusing to bootstrap a target project inside the Aegis source repository."
    )


def ensure_source_clean(root: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    if result.stdout.strip():
        raise SystemExit(
            "Aegis source worktree is dirty; commit or remove local changes before bootstrap."
        )


def read_source_commit(root: Path) -> str:
    """Read the exact Aegis source HEAD used as the bootstrap provenance checkpoint."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"Aegis source HEAD is not a valid commit SHA: {commit!r}")
    return commit


def verify_source_checkpoint(root: Path, expected_commit: str) -> None:
    """Require the source to remain clean and at the exact captured commit."""
    ensure_source_clean(root)
    actual_commit = read_source_commit(root)
    if actual_commit != expected_commit:
        raise SystemExit(
            "Aegis source commit changed during bootstrap: "
            f"expected {expected_commit}, got {actual_commit}."
        )



def _resolve_registry_skill_path(root: Path, raw_path: object, skill_name: str) -> Path:
    """Resolve one registry path while keeping the source boundary explicit."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise SystemExit(
            f"Aegis registry skill {skill_name!r} must contain a non-empty relative path."
        )

    candidate = Path(raw_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise SystemExit(
            f"Aegis registry skill {skill_name!r} must use a relative source path without traversal."
        )

    absolute_candidate = (root / candidate).absolute()
    if absolute_candidate.is_symlink():
        raise SystemExit(
            f"Aegis registry skill {skill_name!r} must not reference a symbolic link."
        )

    resolved = (root / candidate).resolve()
    if resolved != absolute_candidate:
        raise SystemExit(
            f"Aegis registry skill {skill_name!r} must not resolve through symbolic links."
        )

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SystemExit(
            f"Aegis registry skill {skill_name!r} resolves outside the Aegis source repository."
        ) from exc
    if not resolved.is_file():
        raise SystemExit(
            f"Aegis registry points to a missing skill: {skill_name} -> {raw_path}"
        )
    return resolved

def load_source_metadata(root: Path) -> tuple[str, dict, dict]:
    version_file = root / "VERSION"
    manifest_file = root / "aegis-manifest.json"
    registry_file = root / "skills" / "registry.json"

    if not version_file.is_file():
        raise SystemExit(f"Missing Aegis VERSION file: {version_file}")
    if not manifest_file.is_file():
        raise SystemExit(f"Missing Aegis manifest: {manifest_file}")
    if not registry_file.is_file():
        raise SystemExit(f"Missing Aegis skill registry: {registry_file}")

    try:
        version = version_file.read_text(encoding="utf-8").strip()
        manifest = load_json_object(manifest_file)
        registry = load_json_object(registry_file)
    except (EvidenceContractError, OSError, UnicodeDecodeError) as exc:
        raise SystemExit(f"Unable to read Aegis source metadata: {exc}") from exc

    if manifest.get("version") != version:
        raise SystemExit("Aegis VERSION and aegis-manifest.json disagree.")
    if registry.get("version") != version:
        raise SystemExit("Aegis VERSION and skills/registry.json disagree.")
    if not isinstance(registry.get("skills"), list):
        raise SystemExit("Aegis skill registry must contain a skills list.")

    required_manifest_keys = (
        "repository",
        "default_work_item_provider",
        "work_item_strategy",
        "optional_integrations",
        "active_knowledge_model",
    )
    missing_manifest_keys = [
        key for key in required_manifest_keys if key not in manifest
    ]
    if missing_manifest_keys:
        raise SystemExit(
            "Aegis manifest is missing required keys: "
            + ", ".join(missing_manifest_keys)
        )

    registry_names: set[str] = set()
    for entry in registry["skills"]:
        if not isinstance(entry, dict):
            raise SystemExit("Every Aegis registry entry must be an object.")
        name = entry.get("name")
        path = entry.get("path")
        if not isinstance(name, str) or not name or not path:
            raise SystemExit("Every Aegis registry entry must contain name and path.")
        if name in registry_names:
            raise SystemExit(f"Duplicate Aegis registry skill name: {name}")
        registry_names.add(name)

        _resolve_registry_skill_path(root, path, name)

    return version, manifest, registry


def inspect_agents_state(
    agents_path: Path,
    template_path: Path,
    previous_state: dict | None,
) -> tuple[bool, str | None]:
    """Determine Aegis AGENTS ownership without claiming user-owned files."""
    state_has_ownership = (
        previous_state is not None
        and "agents_managed" in previous_state
    )
    if state_has_ownership:
        managed = previous_state["agents_managed"]
        checksum = previous_state.get("agents_sha256")
        if managed:
            if not isinstance(checksum, str):
                raise SystemExit("Managed AGENTS state must contain agents_sha256.")
            if agents_path.is_symlink():
                raise SystemExit(
                    f"Refusing to manage symlinked AGENTS.md: {agents_path}"
                )
            if not agents_path.is_file():
                raise SystemExit(
                    f"Managed AGENTS.md is missing: {agents_path}"
                )
            actual = sha256_file(agents_path)
            if actual != checksum:
                raise SystemExit(
                    "Refusing to modify customized managed AGENTS.md; "
                    f"expected {checksum}, got {actual}."
                )
            return True, checksum

        if checksum is not None:
            raise SystemExit(
                "Unmanaged AGENTS state must not contain agents_sha256."
            )
        return False, None

    if not agents_path.exists() and not agents_path.is_symlink():
        return False, None

    if agents_path.is_symlink():
        return False, None

    if agents_path.is_file():
        template_sha = sha256_file(template_path)
        agents_sha = sha256_file(agents_path)
        return agents_sha == template_sha, (
            template_sha if agents_sha == template_sha else None
        )

    return False, None


def load_previous_state(state_path: Path) -> dict | None:
    if not state_path.is_file():
        return None

    try:
        state = load_json_object(state_path)
    except (EvidenceContractError, OSError, UnicodeDecodeError) as exc:
        raise SystemExit(
            f"Existing Aegis state is not valid JSON: {exc}"
        ) from exc

    if not isinstance(state, dict):
        raise SystemExit("Existing Aegis state must contain a JSON object.")

    schema = state.get("schema_version")
    if schema not in {1, STATE_SCHEMA_VERSION}:
        raise SystemExit(
            f"Unsupported existing Aegis state schema: {schema!r}"
        )

    skills = state.get("skills")
    if not isinstance(skills, list) or not all(
        isinstance(name, str) for name in skills
    ):
        raise SystemExit("Existing Aegis state must contain a string skills list.")
    if skills != sorted(set(skills)):
        raise SystemExit("Existing Aegis state skills must be sorted and unique.")

    for name in skills:
        if not SKILL_NAME_PATTERN.fullmatch(name):
            raise SystemExit(f"Invalid skill name in existing Aegis state: {name!r}")

    agents_managed = state.get("agents_managed", False)
    agents_sha256 = state.get("agents_sha256")
    if not isinstance(agents_managed, bool):
        raise SystemExit("Existing Aegis agents_managed must be boolean.")
    if agents_managed:
        if not isinstance(agents_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}",
            agents_sha256,
        ):
            raise SystemExit(
                "Existing managed AGENTS.md requires a lowercase SHA-256 agents_sha256."
            )
    elif agents_sha256 is not None:
        raise SystemExit(
            "Existing unmanaged AGENTS.md state must not contain agents_sha256."
        )

    checksums = state.get("skill_checksums", {})
    if not isinstance(checksums, dict):
        raise SystemExit("Existing Aegis state skill_checksums must be an object.")

    return state


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_managed_root(project: Path, path: Path, label: str) -> None:
    """Reject symlinked managed roots and resolved paths outside the project."""
    current = path
    while current != project:
        if current.is_symlink():
            raise SystemExit(
                f"Refusing to use symlinked {label}: {current}"
            )
        parent = current.parent
        if parent == current:
            raise SystemExit(
                f"{label} is not contained by the project root: {path}"
            )
        current = parent

    resolved = path.resolve()
    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise SystemExit(
            f"{label} resolves outside the project root: {resolved}"
        ) from exc


def validate_existing_managed_path(
    destination: Path,
    expected_checksum: str | None,
    name: str,
) -> None:
    if not destination.exists() and not destination.is_symlink():
        return
    if destination.is_symlink():
        raise SystemExit(
            f"Refusing to manage symlinked Aegis skill path: {destination}"
        )
    if not destination.is_dir():
        raise SystemExit(
            f"Refusing to manage non-directory skill path: {destination}"
        )

    entries = list(destination.iterdir())
    unexpected = [
        entry.name
        for entry in entries
        if entry.name != "SKILL.md" or entry.is_dir()
    ]
    if unexpected:
        raise SystemExit(
            f"Refusing to modify customized Aegis skill {name}; "
            f"unexpected entries: {', '.join(sorted(unexpected))}"
        )

    skill_file = destination / "SKILL.md"
    if skill_file.is_symlink():
        raise SystemExit(
            f"Refusing to manage symlinked Aegis skill file: {skill_file}"
        )
    if expected_checksum and skill_file.is_file():
        actual = sha256_file(skill_file)
        if actual != expected_checksum:
            raise SystemExit(
                f"Refusing to modify customized Aegis skill {name}; "
                "recorded checksum does not match the current file."
            )


def preflight_targets(
    target_root: Path,
    selected_names: set[str],
    previous_state: dict | None,
) -> None:
    previous_skills = set(previous_state["skills"]) if previous_state else set()
    previous_checksums = (
        previous_state.get("skill_checksums", {}) if previous_state else {}
    )

    for name in selected_names:
        destination = target_root / name
        if name in previous_skills:
            expected = previous_checksums.get(name)
            validate_existing_managed_path(destination, expected, name)
        elif destination.is_symlink():
            raise SystemExit(
                f"Refusing to manage symlinked project skill target: {destination}."
            )
        elif destination.exists():
            raise SystemExit(
                f"Refusing to overwrite unowned project skill: {destination}. "
                "Aegis only manages skills previously recorded in its state."
            )

    for name in sorted(previous_skills - selected_names):
        destination = target_root / name
        validate_existing_managed_path(
            destination,
            previous_checksums.get(name),
            name,
        )


def stage_skills(
    root: Path,
    selected: dict[str, Path],
    stage_root: Path,
) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for name, relative_source in selected.items():
        source = root / relative_source
        if not source.is_file():
            raise SystemExit(f"Missing Aegis skill source: {source}")

        staged = stage_root / name / "SKILL.md"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, staged)
        checksums[name] = sha256_file(staged)

    return checksums


def backup_paths(
    project: Path,
    target_root: Path,
    state_path: Path,
    affected_names: set[str],
    backup_root: Path,
) -> tuple[dict[str, Path], Path | None, bool]:
    backups: dict[str, Path] = {}
    for name in sorted(affected_names):
        destination = target_root / name
        if destination.exists():
            backup = backup_root / "skills" / name
            shutil.copytree(destination, backup)
            backups[name] = backup

    state_backup: Path | None = None
    state_existed = state_path.is_file()
    if state_existed:
        state_backup = backup_root / "aegis-version.json"
        shutil.copy2(state_path, state_backup)

    return backups, state_backup, state_existed


def restore_transaction(
    target_root: Path,
    state_path: Path,
    agents_path: Path,
    affected_names: set[str],
    backups: dict[str, Path],
    state_backup: Path | None,
    state_existed: bool,
    agents_created: bool,
) -> None:
    for name in sorted(affected_names):
        destination = target_root / name
        if destination.exists():
            shutil.rmtree(destination)
        backup = backups.get(name)
        if backup:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup, destination)

    if state_path.exists():
        state_path.unlink()
    if state_existed and state_backup:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(state_backup, state_path)

    if agents_created and agents_path.exists():
        agents_path.unlink()


def write_state_atomically(state_path: Path, state: dict) -> None:
    """Persist bootstrap state through the canonical anchored JSON writer."""
    write_json_atomically(
        state,
        state_path,
        error_type=EvidenceContractError,
    )


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    project = args.project.resolve()

    ensure_project_outside_source(root, project)

    if not project.is_dir():
        raise SystemExit(f"Project directory does not exist: {project}")

    ensure_source_clean(root)
    source_commit = read_source_commit(root)
    manifest_version, manifest, _registry = load_source_metadata(root)
    selected = selected_sources(args.preset, args.integration)

    target_root = project / ".agents" / "skills"
    state_root = project / ".aegis"
    state_path = state_root / "aegis-version.json"
    agents_path = project / "AGENTS.md"
    agents_template_path = root / "templates" / "AGENTS.md"

    validate_managed_root(project, target_root, ".agents/skills")
    validate_managed_root(project, state_root, ".aegis")

    previous_state = load_previous_state(state_path)
    agents_managed, agents_sha256 = inspect_agents_state(
        agents_path,
        agents_template_path,
        previous_state,
    )
    preflight_targets(
        target_root=target_root,
        selected_names=set(selected),
        previous_state=previous_state,
    )

    if args.dry_run:
        for name, relative_source in selected.items():
            print(
                f"Would install {root / relative_source} -> "
                f"{target_root / name / 'SKILL.md'}"
            )
        if previous_state:
            for name in sorted(set(previous_state["skills"]) - set(selected)):
                print(f"Would remove stale Aegis skill {target_root / name}")
        return 0

    stage_root = Path(
        tempfile.mkdtemp(prefix=".aegis-bootstrap-stage-", dir=project)
    )
    backup_root = Path(
        tempfile.mkdtemp(prefix=".aegis-bootstrap-backup-", dir=project)
    )

    previous_skills = set(previous_state["skills"]) if previous_state else set()
    affected_names = previous_skills | set(selected)

    backups: dict[str, Path] = {}
    state_backup: Path | None = None
    state_existed = False
    agents_created = False
    mutation_started = False

    try:
        skill_checksums = stage_skills(root, selected, stage_root)
        verify_source_checkpoint(root, source_commit)
        backups, state_backup, state_existed = backup_paths(
            project=project,
            target_root=target_root,
            state_path=state_path,
            affected_names=affected_names,
            backup_root=backup_root,
        )

        mutation_started = True

        stale_skills = sorted(previous_skills - set(selected))
        for name in stale_skills:
            destination = target_root / name
            if destination.exists():
                shutil.rmtree(destination)
                print(f"Removed stale Aegis skill {destination}")

        for name in sorted(selected):
            staged = stage_root / name / "SKILL.md"
            destination = target_root / name / "SKILL.md"
            copy_file_atomically(
                staged,
                destination,
                error_type=EvidenceContractError,
            )
            print(f"Installed {destination}")

        if not agents_path.exists() and not agents_path.is_symlink():
            copy_file_atomically(
                agents_template_path,
                agents_path,
                error_type=EvidenceContractError,
            )
            agents_created = True
            agents_managed = True
            agents_sha256 = sha256_file(agents_path)
            print(f"Installed {agents_path}")
        else:
            print(
                f"Preserved existing {agents_path}; "
                "reconcile Aegis rules manually."
            )

        verify_source_checkpoint(root, source_commit)

        source_repository = manifest.get(
            "repository",
            "KenlikDev/aegis-engineering-os",
        )
        skill_names = sorted(selected)
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "aegis_version": manifest_version,
            "source_repository": source_repository,
            "source_commit": source_commit,
            "source_worktree_clean": True,
            "preset": args.preset,
            "integrations": sorted(
                name for name in selected if name in OPTIONAL_INTEGRATIONS
            ),
            "skills": skill_names,
            "skill_checksums": skill_checksums,
            "agents_managed": agents_managed,
            "agents_sha256": agents_sha256,
            "status": "active",
        }
        write_state_atomically(state_path, state)

    except Exception:
        if not mutation_started:
            raise
        try:
            restore_transaction(
                target_root=target_root,
                state_path=state_path,
                agents_path=agents_path,
                affected_names=affected_names,
                backups=backups,
                state_backup=state_backup,
                state_existed=state_existed,
                agents_created=agents_created,
            )
        except Exception as rollback_error:
            raise SystemExit(
                "Bootstrap failed and automatic rollback also failed: "
                f"{rollback_error}"
            )
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
        shutil.rmtree(backup_root, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
