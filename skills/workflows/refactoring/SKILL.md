---
name: refactoring
description: Perform controlled behavior-preserving refactoring by composing requirements, architecture, implementation, testing, and independent review boundaries.
---

# Refactoring

## Objective

Improve internal structure while preserving the explicitly accepted external behavior and scope of the work item.

Refactoring is not a substitute for feature implementation or bug fixing. When the change intentionally alters product behavior, public contracts, persistence semantics, security posture, or another material outcome, reclassify the work or obtain the required explicit decision.

## Entry conditions

- the authoritative work item is requirements-ready;
- the intended refactoring scope and non-goals are explicit;
- affected components are identified from evidence rather than inferred;
- behavior invariants are explicit enough to verify;
- a baseline can be established through the project testing workflow;
- material architecture decisions have passed the architecture-planning boundary.

## Process

1. Run requirements clarification and resolve blocker questions without inventing decisions.
2. Run architecture planning when the refactor crosses component boundaries or changes durable structure.
3. Record the behavior that must remain unchanged, including relevant public interfaces and observable side effects.
4. Establish a verified baseline with the existing testing workflow.
5. Implement the smallest structural change through the normal task-branch and implementation workflow.
6. Re-run focused and broader declared quality gates as applicable.
7. Compare the resulting behavior and public contracts against the explicit invariants.
8. Perform an independent review focused on semantic preservation, compatibility, duplication, complexity, and regression risk.
9. Record any discovered behavior change as scope change; do not silently absorb it into the refactor.
10. Deliver through the normal review and integration boundaries.

## Testing contract

The refactoring workflow uses `tools/testing.py` and the project-local `.aegis/quality-gates.json` contract.

It never infers commands, weakens required gates, or treats a passing baseline as proof that a later structural change is safe without post-change verification.

## Review focus

The independent review must explicitly consider:

- semantic preservation;
- API and interface compatibility;
- persistence and serialization compatibility;
- concurrency and ordering assumptions;
- error behavior;
- performance characteristics;
- removal of duplicated or unnecessary complexity;
- regression evidence;
- scope discipline.

## Safety

The workflow never:

- invents product behavior;
- silently expands scope;
- converts refactoring into feature work;
- bypasses required quality gates;
- rewrites protected branches;
- treats unverified assumptions as behavior invariants.

Implementation remains subject to the existing task-branch, OpenHands, delivery, and integration controls.
