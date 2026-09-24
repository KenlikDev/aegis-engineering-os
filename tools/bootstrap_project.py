#!/usr/bin/env python3
"""Install a controlled Aegis skill set into a target repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


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

    version = version_file.read_text(encoding="utf-8").strip()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    registry = json.loads(registry_file.read_text(encoding="utf-8"))

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
        name = entry.get("name")
        path = entry.get("path")
        if not name or not path:
            raise SystemExit("Every Aegis registry entry must contain name and path.")
        if name in registry_names:
            raise SystemExit(f"Duplicate Aegis registry skill name: {name}")
        registry_names.add(name)

        registry_path = root / path
        if not registry_path.is_file():
            raise SystemExit(
                f"Aegis registry points to a missing skill: {name} -> {path}"
            )

    return version, manifest, registry



def load_previous_state(state_path: Path) -> dict | None:
    if not state_path.is_file():
        return None

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Existing Aegis state is not valid JSON: {exc}"
        ) from exc

    if not isinstance(state, dict):
        raise SystemExit("Existing Aegis state must contain a JSON object.")
    if state.get("schema_version") != 1:
        raise SystemExit(
            f"Unsupported existing Aegis state schema: {state.get('schema_version')!r}"
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

    return state


def reconcile_previous_skills(
    target_root: Path,
    previous_skills: set[str],
    selected_skills: set[str],
    dry_run: bool,
) -> None:
    stale_skills = sorted(previous_skills - selected_skills)
    for name in stale_skills:
        destination = target_root / name
        if not destination.exists():
            continue
        if not destination.is_dir():
            raise SystemExit(
                f"Refusing to remove non-directory managed skill path: {destination}"
            )

        entries = list(destination.iterdir())
        unexpected = [
            entry.name
            for entry in entries
            if entry.name != "SKILL.md" or entry.is_dir()
        ]
        if unexpected:
            raise SystemExit(
                f"Refusing to remove customized managed skill {name}; "
                f"unexpected entries: {', '.join(sorted(unexpected))}"
            )

        if dry_run:
            print(f"Would remove stale Aegis skill {destination}")
        else:
            shutil.rmtree(destination)
            print(f"Removed stale Aegis skill {destination}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    project = args.project.resolve()

    if not project.is_dir():
        raise SystemExit(f"Project directory does not exist: {project}")

    manifest_version, manifest, _registry = load_source_metadata(root)
    selected = selected_sources(args.preset, args.integration)

    target_root = project / ".agents" / "skills"
    state_root = project / ".aegis"
    state_path = state_root / "aegis-version.json"
    previous_state = load_previous_state(state_path)
    previous_skills = set(previous_state["skills"]) if previous_state else set()

    reconcile_previous_skills(
        target_root=target_root,
        previous_skills=previous_skills,
        selected_skills=set(selected),
        dry_run=args.dry_run,
    )

    for name, relative_source in selected.items():
        source = root / relative_source

        if not source.is_file():
            raise SystemExit(f"Missing Aegis skill source: {source}")

        destination = target_root / name / "SKILL.md"

        if args.dry_run:
            print(f"Would install {source} -> {destination}")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"Installed {destination}")

    if not args.dry_run:
        state_root.mkdir(parents=True, exist_ok=True)

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

        source_repository = manifest.get(
            "repository",
            "KenlikDev/aegis-engineering-os",
        )
        skill_names = sorted(selected)
        skill_checksums = {
            name: sha256_file(target_root / name / "SKILL.md")
            for name in skill_names
        }
        state = {
            "schema_version": 1,
            "aegis_version": manifest_version,
            "source_repository": source_repository,
            "source_commit": commit,
            "preset": args.preset,
            "integrations": sorted(
                name for name in selected if name in OPTIONAL_INTEGRATIONS
            ),
            "skills": skill_names,
            "skill_checksums": skill_checksums,
            "status": "active",
        }
        (state_root / "aegis-version.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        source_agents = root / "templates" / "AGENTS.md"
        target_agents = project / "AGENTS.md"
        if target_agents.exists():
            print(
                f"Preserved existing {target_agents}; "
                "reconcile Aegis rules manually."
            )
        else:
            shutil.copy2(source_agents, target_agents)
            print(f"Installed {target_agents}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
