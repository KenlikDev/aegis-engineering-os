---
name: workflow-composition
description: Construct a deterministic workflow sequence from an explicitly classified work-item kind without inferring scope or executing actions.
---

# Workflow Composition

## Objective

Turn an explicitly classified work-item kind into an ordered set of Aegis workflow capabilities.

The composition layer is a planning boundary. It does not execute workflows, change lifecycle state, mutate project files, or select product scope.

## Supported kinds

The current compositions are:

- `feature`;
- `bug-fix`;
- `refactoring`;
- `ci-remediation`.

The kind must already be established by the work context. Aegis must not infer it from free-form task text.

## Contract

The composition contains:

- ordered steps;
- whether a step is required or conditional;
- the explicit condition for conditional steps.

Every referenced capability must exist in `skills/registry.json`.

Conditional steps remain visible in the composition. The orchestrator decides whether their applicability condition is satisfied using current evidence.

## Execution

Inspect a composition without performing any workflow:

    python3 tools/workflow_composition.py --kind refactoring

The command is read-only and deterministic.

## Safety

The workflow never:

- infers a work-item kind from user text;
- changes scope, priority, or acceptance criteria;
- executes project commands;
- mutates work-item state;
- changes Git refs;
- targets protected branches.

Workflow composition is intentionally separate from workflow execution.
