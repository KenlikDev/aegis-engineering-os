---
name: requirements-clarification
description: Inspect a work-item document for missing requirements and produce deterministic clarification questions without inventing user decisions.
---

# Requirements Clarification

## Objective

Verify that a non-trivial work item contains enough explicit information to enter implementation planning.

## Required evidence

The canonical work-item document is checked for:

- concrete title;
- explicit intent and desired outcome;
- in-scope work;
- out-of-scope work;
- at least one observable acceptance criterion;
- verification plan.

Dependencies and risks are reported as warnings when absent, but do not block readiness by themselves.

## Decision ownership

The workflow never invents:

- acceptance criteria;
- product priorities;
- business commitments;
- scope decisions;
- technical choices owned by the user.

Missing decisions become explicit questions.

## Output

tools/requirements_clarification.py returns structured JSON containing:

- ready or needs-clarification status;
- deterministic question ids;
- severity;
- affected section;
- clarification question;
- observable evidence.

Exit codes:

- 0 — requirements are ready; warnings may still be present;
- 2 — one or more blocker-level clarifications are required;
- 1 — input or processing error.

## Safety

The workflow is read-only. It never changes the work item, Git state, issue tracker, or project files.
