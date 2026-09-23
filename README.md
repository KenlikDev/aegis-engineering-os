# Aegis Engineering OS

A modular engineering operating system for autonomous software development with a local LLM and OpenHands.

> Status: Experimental alpha  
> Version: 0.1.0-alpha.1

Aegis defines the engineering rules, roles, workflows, skills, quality gates, decision authority, project memory, Git/GitHub policy, version verification, and offline behavior used by an autonomous development agent.

## Core principles

- The user communicates with Aegis in Russian.
- Code, code comments, Git commits, pull requests, ADRs, and canonical engineering documentation are written in professional English.
- Russian explanations are supporting material for the product owner and are not a second engineering source of truth.
- The agent works on task branches and must not directly modify protected `develop` or `main`.
- Technical implementation can be delegated to the AI; product and high-impact decisions remain with the user unless explicitly delegated.
- Every important change is verified before integration.
- New knowledge is treated as candidate knowledge until validated.
- A known-good local Aegis version remains usable when GitHub or the internet is unavailable.
- The agent must verify the actual technology versions used by a project before implementing against version-sensitive APIs or behavior.

## Repository structure

- `00-constitution/` — non-negotiable operating rules.
- `01-orchestrator/` — autonomous execution model.
- `02-roles/` — role responsibilities.
- `03-workflows/` — repeatable engineering workflows.
- `skills/` — canonical reusable skills.
- `05-quality-gates/` — verification requirements.
- `06-git-github/` — Git and GitHub governance.
- `07-knowledge/` — knowledge lifecycle and evidence.
- `08-offline/` — offline and update strategy.
- `templates/` — files copied or generated into projects.
- `tools/` — local validation and project bootstrap tooling.
- `.agents/skills/` — Aegis repository-local skills recognized by OpenHands.

See `docs/architecture/overview.md` for the current system design.
