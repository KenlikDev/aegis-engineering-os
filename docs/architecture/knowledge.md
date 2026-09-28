# Knowledge Gap Architecture

## Purpose

Knowledge-gap handling lets Aegis improve reusable engineering knowledge without allowing an unverified discovery to replace active guidance.

## Candidate boundary

tools/knowledge_gap.py stores a structured candidate record outside the active skill registry.

Each candidate records:

- candidate id;
- global or project scope;
- missing capability;
- observed problem;
- proposed change;
- HTTPS provenance references;
- creation timestamp;
- SHA-256 hash of the original candidate payload.

The original candidate payload is never rewritten during validation or rejection.

## Validation boundary

A candidate can move from candidate to validated only when:

- a focused scenario is explicitly described;
- at least one HTTPS evidence reference is supplied;
- the validation outcome is passed.

Validation evidence is sanitized before storage. Secret-like values are rejected in the original candidate and redacted from validation evidence. The stored validation payload has its own SHA-256 hash so later edits fail closed.

## Rejection

A candidate or validated record may be rejected with an explicit reason.

Rejection does not mutate any active skill or registry entry.

## Active knowledge safety

The candidate registry supports only:

candidate -> validated
candidate -> rejected
validated -> rejected

It does not implement validated -> known-good or known-good -> active.

Those transitions remain separate controlled operations so a successful experiment cannot silently change Aegis behavior globally.

## Provider and storage model

The candidate registry is deliberately provider-neutral and filesystem-backed. A project may store project-scoped candidates in the project workspace; global candidates belong to the Aegis repository.

No external issue tracker mutation is required to create a candidate record. Work-item linkage can be added by a higher-level workflow when an external tracker is authoritative.

## Lifecycle position

knowledge gap detected
-> candidate record
-> focused validation
-> validated candidate
-> controlled knowledge promotion

A failed candidate stays rejected and cannot become active by accident.
