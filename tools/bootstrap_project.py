#!/usr/bin/env python3
"""Install a controlled Aegis skill set into a target repository."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


SKILL_SOURCES = {
    "aegis-orchestrator": Path("01-orchestrator/SKILL.md"),
    "version-verification": Path("skills/version-verification/SKILL.md"),
    "git-hygiene": Path("skills/git-hygiene/SKILL.md"),
    "user-communication": Path("skills/user-communication/SKILL.md"),
    "offline-operation": Path("skills/offline-operation/SKILL.md"),
    "product-discovery": Path("skills/product-discovery/SKILL.md"),
    "skill-authoring": Path("skills/skill-authoring/SKILL.md"),
    "knowledge-gap": Path("skills/knowledge-gap/SKILL.md"),
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


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    project = args.project.resolve()

    if not project.is_dir():
        raise SystemExit(f"Project directory does not exist: {project}")

    target_root = project / ".agents" / "skills"
    state_root = project / ".aegis"

    for name, relative_source in selected_sources(args.preset, args.integration).items():
        source = root / relative_source
        destination = target_root / name / "SKILL.md"

        if not source.is_file():
            raise SystemExit(f"Missing Aegis skill source: {source}")

        if args.dry_run:
            print(f"Would install {source} -> {destination}")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"Installed {destination}")

    if not args.dry_run:
        manifest = json.loads(
            (root / "aegis-manifest.json").read_text(encoding="utf-8")
        )
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
        state = {
            "aegis_version": manifest["version"],
            "source_repository": source_repository,
            "source_commit": commit,
            "preset": args.preset,
            "integrations": sorted(set(args.integration)),
            "status": "active",
        }
        (state_root / "aegis-version.json").write_text(
            json.dumps(state, indent=2) + "\n",
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
