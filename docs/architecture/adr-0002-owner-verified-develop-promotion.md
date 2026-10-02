# ADR-0002: Gate develop promotion on owner verification of ai/integration

## Status

Accepted

## Context

The autonomous engineering boundary ends at `ai/integration`. The repository previously used a synthetic promotion snapshot branch, such as `ai/<work-item>-develop-promotion`, to prepare squash-only promotion into `develop`.

The product owner requires a stricter human checkpoint: autonomous work may enter `ai/integration), the owner then verifies the exact current `ai/integration` state, and only that verified state may be promoted into `develop`. A temporary branch must not become the source of the develop merge, and no develop promotion pull request may be created before the owner verification.

## Decision

Develop promotion uses a direct pull request:

`ai/integration -> develop`

The preparation boundary is `tools/develop_promotion.py`. It requires an explicit owner-verified source SHA and an authoritative work item already in lifecycle state `integration`, checks promotion readiness, and performs a fresh exact-SHA readiness recheck immediately before the direct PR write so concurrent integration changes are rejected as stale. The verified SHA is recorded in the PR body.

The former develop snapshot path in `tools/promotion_snapshot.py` is blocked. The snapshot mechanism remains available only for the existing main release-promotion flow.

Promotion synchronization accepts direct `ai/integration -> develop` pull requests and requires the recorded verified source SHA to equal the PR head SHA at synchronization time. A stale or advanced integration branch therefore fails closed rather than being treated as the previously reviewed checkpoint.

The owner remains responsible for the human verification and the protected-branch merge. Aegis never approves or merges `develop` or `main`.

## Consequences

- The exact `ai/integration` revision reviewed by the owner is visible in the develop PR.
- A develop PR cannot be prepared through the former temporary snapshot branch mechanism.
- Advancing `ai/integration` after owner verification invalidates the checkpoint until a fresh verification is supplied.
- Develop promotion no longer depends on a synthetic two-parent snapshot commit.
- Main release promotion is unchanged unless a separate release-governance decision revises it.

## Alternatives considered

A temporary develop promotion branch was rejected because it obscured the required owner verification boundary and allowed a derived ref to become the merge source.

An implicit UI-only owner review was rejected as insufficiently reproducible for automation because the preparation tool needs a concrete, externally supplied source revision to verify.

## Verification

Unit tests cover the owner-gated direct promotion path, stale verified SHA rejection, protected-target enforcement, direct PR reuse, and rejection of develop targets by the former snapshot tool. Promotion synchronization tests cover direct develop PR acceptance, missing owner-verification evidence, and verification/head drift.
