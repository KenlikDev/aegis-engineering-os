---
name: knowledge-gap-creation
description: Create and validate a versioned knowledge-gap candidate without replacing active Aegis knowledge.
---

# Knowledge Gap Creation

## Objective

Turn a discovered knowledge gap into a traceable candidate record that can be validated independently from active knowledge.

## Required evidence

A candidate must contain:

- a stable candidate id;
- explicit scope: global or project;
- a concise capability name;
- the observed problem;
- the proposed change;
- at least one HTTPS provenance reference.

Validation requires:

- a focused scenario;
- at least one HTTPS evidence reference;
- an explicit passed outcome.

## Lifecycle

candidate -> validated

candidate -> rejected

validated -> rejected

A validated candidate is not automatically known-good or active.

## Safety rules

- Do not modify skills/registry.json while creating a candidate.
- Do not silently overwrite an active skill.
- Preserve the original candidate payload and its SHA-256 hash.
- Preserve validation evidence and its SHA-256 hash.
- Reject tampered candidate records.
- Redact secret-like values before serializing validation evidence.

## Implementation

The executable boundary is tools/knowledge_gap.py.

Exit codes:

- 0 — operation completed;
- 1 — invalid input, persistence, or record error.

The candidate store belongs under .aegis/knowledge/candidates by default.
