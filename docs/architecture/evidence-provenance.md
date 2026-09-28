# Evidence Provenance Architecture

## Purpose

Aegis needs a provider-neutral way to persist material observations without confusing an observation with the operation that produced it.

The evidence provenance envelope is the smallest common contract for state-dependent evidence. Existing subsystem-specific reports remain authoritative within their own workflows; this envelope gives future adapters a stable provenance shape.

## Envelope

A canonical evidence record contains:

- \`schema_version\` — contract version;
- \`evidence_id\` — SHA-256 identity of the canonical unsigned payload;
- \`kind\` — lowercase kebab-case evidence category;
- \`source\` — authoritative system or local source description;
- \`subject\` — observed object or state target;
- \`revision\` — commit, object revision, run identifier, or equivalent when available;
- \`observed_at\` — ISO-8601 timestamp with an explicit timezone, normalized to UTC;
- \`status\` — \`verified\`, \`failed\`, \`pending\`, or \`unknown\`;
- \`result\` — structured observed result;
- \`uncertainty\` — explicit unresolved limitations;
- \`references\` — optional HTTPS references;
- \`artifact_sha256\` — optional hash of an external/local evidence artifact;
- \`evidence_sha256\` — the same canonical SHA-256 identity stored for integrity checking.

The self-hash covers the normalized payload with \`evidence_id\` and \`evidence_sha256\` excluded. This avoids a circular hash while keeping the identity deterministic.

## Recording

\`tools/state_verification.py record\` accepts a JSON observation and writes the canonical envelope.

The recorder:

1. rejects duplicate JSON keys and ambiguous numeric constants;
2. validates schema and bounded field sizes;
3. normalizes the observation timestamp to UTC;
4. rejects secret-like field names and common credential signatures;
5. requires HTTPS references;
6. computes the canonical SHA-256 identity;
7. writes the evidence artifact without mutating the observed system.

The tool records explicit observations. It does not itself contact GitHub, CI, Jira, or another provider.

## Validation

\`tools/state_verification.py validate\` reads an evidence artifact and recomputes its identity.

A validation failure means the artifact cannot be trusted as unchanged evidence. A successful validation confirms the artifact is structurally valid and internally consistent; it does not upgrade the original observation beyond what its \`source\`, \`revision\`, and \`status\` establish.

## Timestamp semantics

Observation time is supplied by the observer and must include an explicit timezone. Equivalent timestamps are normalized to UTC before hashing, so \`2026-09-28T20:00:00+02:00\` and \`2026-09-28T18:00:00Z\` produce the same evidence identity when all other fields are identical.

The contract does not generate an observation timestamp because doing so would blur the boundary between when a fact was observed and when an artifact was later persisted.

## Security boundary

Evidence is an information artifact and must not become a credential store.

The contract rejects:

- secret-like object keys such as token, password, secret, credential, and private-key fields;
- common API token and bearer-token signatures;
- non-HTTPS reference links;
- oversized or malformed input;
- duplicate JSON keys that could produce parser-dependent meaning.

This is intentionally defensive rather than a guarantee of complete secret detection.

## Relationship to state verification

The \`state-verification\` skill remains responsible for deciding when fresh authoritative observation is required, how conflicting observations are handled, and how user claims differ from observed facts.

The executable evidence boundary only standardizes the representation and integrity of an observation. Provider integrations remain separate and must supply authoritative observations before an envelope may be marked \`verified\`.

## Relationship to existing evidence formats

Quality-gate runs, CI diagnosis, security review, knowledge-gap records, and version verification currently expose specialized evidence structures.

Promotion readiness, release readiness, and version verification now have explicit adapters in `tools/evidence_adapters.py`. They preserve their specialized result schemas while optionally emitting the canonical provenance envelope.

Version verification preserves each source SHA-256 and maps `external_verification_pending` to canonical `pending` status plus explicit uncertainty. The specialized version-evidence artifact remains the source consumed by implementation readiness; the adapted artifact can additionally participate in evidence bundles.

Implementation readiness now has an explicit adapter as well. It preserves the specialized gate result while mapping blocked readiness to `failed` and pending external compatibility to `pending`.

Testing now has an explicit adapter as well. It preserves the already-redacted quality-gate result and keeps failed required gates canonical `failed`.

Security review now has an explicit adapter as well. It preserves deterministic findings and maps any high-severity finding to canonical `failed` without exposing credential material.

CI diagnosis now has an explicit adapter as well. It preserves exact workflow-run provenance and maps inconclusive diagnosis to canonical `unknown` with explicit uncertainty.

OpenHands execution now has an explicit adapter as well. It preserves the already-redacted conversation state and events; finished maps to canonical `verified`, while error/stuck/blocked map to `failed` with explicit uncertainty. Secret-like keys are removed before canonical validation.

Lifecycle mutations now have an explicit adapter as well. It preserves provider, operation, work-item identity, state transition, verification state, reference, and identifier. Verified mutations become `verified`; unverified mutations remain `unknown` with explicit read-after-write uncertainty.

Knowledge-gap records now have an explicit adapter as well. It preserves candidate provenance and controlled lifecycle state; candidate/validated/rejected map to `pending`/`verified`/`failed`, without treating verified candidate knowledge as active guidance.

The adapters do not reinterpret existing reports or change readiness decisions. Future subsystem adapters must follow the same explicit boundary: preserve the subsystem schema, identify the exact observed revision, and retain meaningful uncertainty rather than silently upgrading evidence.

Canonical evidence artifacts may be composed by the separate evidence-bundle boundary. Bundling preserves member identity and does not infer decision completeness.

A separate evidence-set requirements consumer can validate whether an explicitly declared selector set is satisfied by a bundle. This is deliberately downstream of bundle integrity validation and does not define which evidence a product or engineering gate should require; those requirements must be supplied explicitly by the owning gate or workflow.
