# ADR-0003: Enforce the owner-verified develop source through required CI

## Status

Accepted

## Context

Develop promotion uses a direct pull request from `ai/integration` to `develop`. The promotion tool records the exact source SHA verified by the owner.

Because a pull request tracks the live head branch, later autonomous integration merges can advance the PR head after the owner verification. Tool-side checks can detect this when the promotion tool is invoked again, but they do not by themselves prevent an already-open PR from remaining merge-eligible through the normal protected-branch check path.

## Decision

For a direct `ai/integration -> develop` pull request, the `Validate Aegis` workflow runs `tools/validate_develop_promotion.py`.

The validator is intentionally read-only. It activates only for direct `ai/integration -> develop` pull requests and requires exactly one authoritative `Work item: #<id>` marker plus exactly one `Verified source SHA` marker in the PR body. The work-item identifier must be a positive integer; the source SHA must be a valid 40-character lowercase commit SHA and must equal the current pull-request head SHA.

The specialized gate runs before the general repository validation steps. A drifted direct promotion therefore fails the required `Validate Aegis` check.

Other pull-request flows and main release-promotion snapshots are unchanged.

## Consequences

- Owner verification remains explicit and is represented by a concrete commit SHA.
- Advancing `ai/integration` invalidates the existing develop promotion check path until a new owner verification is supplied.
- The enforcement remains within the existing read-only validation workflow and does not require write permissions or protected-branch mutation.
- Direct develop promotion still remains human-controlled; Aegis never approves or merges `develop`.

## Verification

Unit tests cover matching source/head equality, work-item marker presence and uniqueness, SHA drift, missing and duplicate markers, malformed heads, unrelated pull-request flows, and the CLI event-file boundary.
