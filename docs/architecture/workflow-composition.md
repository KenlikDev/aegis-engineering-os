# Workflow Composition Architecture

## Purpose

Workflow composition is the planning boundary between work-item classification and workflow execution.

It solves a specific orchestration problem: multiple reusable workflows now exist, so the orchestrator needs an explicit sequence rather than relying on passive skill availability.

## Input authority

The work-item kind is an explicit input.

Current supported kinds:

- `feature`;
- `bug-fix`;
- `refactoring`;
- `ci-remediation`.

The composition layer does not classify free-form user text because that could silently change the intended engineering mode.

## Composition model

Each composition is an ordered list of capabilities.

A step contains:

- capability name;
- capability kind;
- required/conditional status;
- condition text when conditional.

Conditional architecture and security boundaries are represented explicitly instead of being removed from the plan before evidence is available.

## Registry integrity

The composition builder validates every referenced capability against `skills/registry.json`.

The registry is parsed through the shared bounded strict JSON object loader. Duplicate keys, non-standard JSON constants, malformed UTF-8, and oversized registry input are rejected before any capability names are interpreted.

An unregistered capability is a hard configuration error. The planner never silently substitutes another skill.

## Current compositions

### Feature

work-item lifecycle
-> requirements clarification
-> project discovery
-> version verification
-> architecture planning (when applicable)
-> feature implementation
-> testing
-> security review (when applicable)
-> code review
-> integration delivery (when implementation changes are ready)

### Bug fix

work-item lifecycle
-> requirements clarification
-> project discovery
-> version verification
-> architecture planning (when applicable)
-> bug fix
-> testing
-> security review (when applicable)
-> code review
-> integration delivery (when implementation changes are ready)

### Refactoring

work-item lifecycle
-> requirements clarification
-> project discovery
-> version verification
-> architecture planning (when applicable)
-> refactoring
-> testing
-> security review (when applicable)
-> code review
-> integration delivery (when implementation changes are ready)

### CI remediation

work-item lifecycle
-> requirements clarification
-> project discovery
-> version verification
-> architecture planning (when applicable)
-> CI remediation
-> testing
-> security review (when applicable)
-> code review
-> integration delivery (when implementation changes are ready)

Version verification is a registered engineering skill step rather than a separate workflow. It establishes the actual toolchain before architecture-sensitive decisions are made.

The composition is a reusable plan, not permission to bypass any downstream workflow contract.

## Relationship to Orchestrator

The top-level orchestrator:

1. establishes or receives the explicit work-item kind;
2. builds the composition;
3. loads only the referenced skills and their required deep references;
4. evaluates conditional steps against current evidence;
5. executes the selected workflows in order;
6. preserves each workflow's own authority and safety boundary.

A missing or ambiguous work-item kind is an input problem, not permission to guess.

## Canonical provenance

A successful explicit composition can be adapted into the canonical evidence envelope with `--canonical-evidence-output`. The adapter preserves the work-item kind, every ordered step, step kind, required/conditional state, condition text, and required-step projection.

Because `compose_workflow` rejects unsupported kinds and unregistered capabilities, successful composition output is canonical `verified`. The adapter does not reinterpret conditional applicability.

## Safety

The composition builder is read-only. It never:

- executes commands;
- changes files;
- changes work-item state;
- creates branches or pull requests;
- merges commits;
- changes protected branches;
- invents product decisions.
