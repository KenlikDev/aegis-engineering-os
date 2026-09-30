---
name: knowledge-gap
description: Detect missing engineering knowledge, create candidate guidance, validate it, and safely promote successful knowledge improvements.
---

# Knowledge Gap Handling

## Trigger

Invoke when the task requires a role, technology, workflow, policy, or practice for which Aegis has no adequate skill.

## Protocol

1. Describe the missing capability.
2. Search existing Aegis knowledge before creating anything.
3. Determine whether the gap is project-specific or globally reusable.
4. Research authoritative sources when available.
5. Create a candidate skill or reference.
6. Validate syntax and internal consistency.
7. Test the candidate on a focused scenario.
8. Record the evidence.
9. Promote only when validation supports the change.
10. Verify persisted transition-history integrity before emitting lifecycle provenance.
11. Keep the old active knowledge available for rollback.

## Scope rule

Project-specific knowledge belongs in project-local guidance. General reusable knowledge belongs in the global skill library.

## Failure rule

A failed candidate must never silently replace an active skill.


## Persistence integrity

Candidate and validation payloads carry independent SHA-256 provenance. Persisted lifecycle transitions are schema-checked and chained from the previous state to the current record state, and new records carry a SHA-256 hash of the persisted transition history. Legacy records without that hash remain readable but their canonical provenance must retain explicit transition-integrity uncertainty until the record is rewritten.

The knowledge-gap workflow still does not activate knowledge automatically. Transition-history verification protects the audit record; it does not authorize promotion.
