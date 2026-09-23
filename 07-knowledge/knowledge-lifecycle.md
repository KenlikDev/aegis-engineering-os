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
