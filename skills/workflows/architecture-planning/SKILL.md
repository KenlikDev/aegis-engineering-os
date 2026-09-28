---
name: architecture-planning
description: Produce a deterministic, read-only architecture plan from a clarified ready work item without inventing product or user-owned decisions.
---

# Architecture Planning

## Objective

Turn a requirements-clarified ready work item into a structured architecture plan before implementation.

## Entry conditions

- the canonical work-item Markdown exists and is readable;
- requirements clarification has no blocker-level questions;
- when lifecycle verification is requested, the authoritative work item is exactly in ready state;
- actual project versions and constraints remain authoritative and must be verified before version-sensitive decisions.

## Planning contract

The workflow separates:

- **explicit evidence** copied from the work item;
- **technical deductions** derived deterministically from that evidence;
- **user-owned decisions** that must be answered by the user or an authoritative project source;
- **blockers** that prevent an implementation-ready architecture plan.

The workflow records:

- constraints;
- architecture boundaries;
- affected components explicitly identified by the work item;
- non-goals;
- ADR needs;
- unresolved questions.

It never invents product scope, priority, acceptance criteria, business commitments, or technical decisions owned by the user.

## Execution

Run:

    python3 tools/architecture_planning.py path/to/work-item.md

To enforce lifecycle readiness through the configured GitHub Issues provider:

    GITHUB_TOKEN="$TOKEN" python3 tools/architecture_planning.py \
      path/to/work-item.md \
      --work-item-repository OWNER/REPO \
      --work-item-id 123

The core planning contract is provider-neutral. GitHub Issues is only the current lifecycle adapter.

## Output

The tool emits deterministic JSON containing:

- ready or blocked status;
- requirements status;
- explicit evidence;
- deterministic technical deductions;
- constraints and boundaries;
- affected components;
- ADR needs;
- non-goals;
- user-owned decisions;
- blockers.

Exit codes:

- 0 — architecture plan is ready for implementation planning;
- 2 — architecture-critical information is missing or requirements remain blocked;
- 1 — input, lifecycle, or processing error.

## Safety

The workflow is read-only. It never changes the work item, issue tracker, Git refs, project files, code, or protected branches.
