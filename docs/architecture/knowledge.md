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

Validation evidence is sanitized before storage. Secret-like values are rejected in the original candidate and redacted from validation evidence. The stored validation payload has its own SHA-256 hash so later edits fail closed. The persisted lifecycle transition history has an independent SHA-256 hash as well.

## Persistence integrity

Knowledge-gap records use the shared bounded strict JSON loader, which rejects duplicate keys and non-standard JSON constants before state interpretation. Record writes use the shared anchored atomic JSON writer, including no-follow directory traversal and same-directory replacement, so a failed or redirected write cannot publish a partial record or follow a symlinked destination path.

This persistence contract is separate from the knowledge lifecycle contract: it protects the stored record without changing candidate, validation, or rejection semantics. Transition entries are schema-checked, their `from -> to` chain must be continuous, and the final transition must match the persisted record state. Legacy records that predate `transitions_sha256` remain readable, but canonical provenance marks their transition-history integrity as unknown until the record is rewritten.

## Canonical provenance

Knowledge-gap records can be adapted into canonical evidence through the `knowledge_gap_evidence` adapter.

The adapter preserves candidate identity, scope, capability, problem, original candidate SHA-256, validation metadata, redacted validation evidence, lifecycle transitions, and the transition-history SHA-256 when available.

Canonical status mapping is explicit:

- candidate -> `pending`;
- validated -> `verified`;
- rejected -> `failed` with explicit uncertainty that the candidate must not be treated as active knowledge.

This mapping describes the recorded knowledge-gap lifecycle. It does not authorize activation or alter the candidate registry.

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
