# Knowledge Lifecycle

Aegis treats instructions as versioned engineering assets.

## States

untrusted -> candidate -> validated -> known-good -> active

## Promotion rules

- One bad task must not immediately change active global knowledge.
- Candidate skills include provenance and version metadata.
- Significant changes have regression scenarios.
- Promotion preserves the previous known-good version.
- Prefer official documentation, primary repositories, project source, tests, and reproducible experiments.


## Executable candidate registry

The first executable stage of knowledge-gap handling is tools/knowledge_gap.py.

Candidate records are stored outside skills/ so they cannot silently become active knowledge. Each record preserves the original candidate payload and its SHA-256 provenance hash.

The supported lifecycle is:

candidate -> validated
candidate -> rejected
validated -> rejected

Validation requires an explicit focused scenario and at least one HTTPS evidence reference. Validation evidence is redacted before storage and protected with its own SHA-256 hash.

A validated candidate is not automatically promoted to known-good or active. Activation remains a separate controlled operation.
