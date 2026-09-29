# Security Review Architecture

## Purpose

Security review is a read-only gate before integration or promotion.

It produces deterministic findings from observable repository state. A finding is evidence of a specific rule violation, not a statement that the whole repository is secure or insecure.

## Checks

tools/security_review.py reviews:

- GitHub Actions trust-boundary triggers;
- explicit workflow permissions;
- broad or unnecessary write permissions;
- third-party action pinning;
- GitHub API version headers;
- executable subprocess security;
- destructive Git operations;
- direct hardcoded writes to protected refs;
- high-confidence credential patterns.

## Severity model

High findings block the review. Medium findings are visible but do not block the review alone.

## Safety boundary

The review reads repository files only. It never changes code or configuration, creates issues, changes branches, modifies GitHub permissions, or prints matched credential values.

## Canonical provenance

The read-only review can emit its existing result into the canonical evidence envelope with `--canonical-evidence-output`. The adapter preserves finding rule IDs, severity, repository-relative paths, line numbers, messages, and the deterministic summary.

A review with any high-severity finding is canonical `failed`. A review without high-severity findings is canonical `verified`, while medium and low findings remain explicitly present in the result.

This output is additive and does not alter security-review findings or exit-code semantics.

## Lifecycle position

implementation
-> code review
-> security review
-> quality verification
-> integration

Security review can also be invoked before promotion when a high-impact change crosses a trust boundary.


## Network and filesystem boundaries

Local runtime preflight rejects HTTP redirects because it may send an Agent Server session authentication header to the selected local endpoint. Redirects therefore cannot silently move that header to another origin.

Managed bootstrap roots and skill paths reject symbolic links, including broken symbolic links, before mutation. The `.agents/skills` and `.aegis` roots are checked for symlinked ancestors and for resolved paths outside the project before state access or installation. When Aegis installs its own AGENTS.md, the project state records explicit ownership and a SHA-256 checksum; verification and subsequent bootstrap runs fail closed on tampering or symlink substitution. A pre-existing project-owned AGENTS.md remains unmanaged and is never overwritten or falsely attributed to Aegis. Legacy AGENTS ownership classification computes the observed file digest once and reuses that exact digest for the ownership decision, avoiding split-read provenance. Canonical evidence, quality-gate, version-verification, evidence-bundle, managed-execution, and testing evidence writers reject symbolic-link destinations and persist JSON through atomic same-directory replacement anchored to the opened destination directory. Managed execution validates its requested evidence output before creating a task branch or starting OpenHands. These checks preserve the declared filesystem boundary rather than relying on the final resolved path alone.
