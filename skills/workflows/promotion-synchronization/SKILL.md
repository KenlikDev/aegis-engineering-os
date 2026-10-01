---
name: promotion-synchronization
description: Synchronize a verified human-controlled promotion merge into the Aegis work-item lifecycle without approving or merging protected branches.
---

# Promotion Synchronization

## Objective

Advance an integrated work item to done only after a promotion pull request has actually merged into a protected develop or main branch.

## Required evidence

1. The work item is in integration.
2. The promotion pull request number is explicit.
3. For develop, the pull-request head is ai/integration and its owner-verification marker names the same source SHA as the PR head. For main, the pull-request head matches ai/<work-item>-main-promotion.
4. The pull-request base matches the selected protected target.
5. The pull request is closed and actually merged.
6. A merge commit SHA is present.
7. The target branch is still protected.
8. A GitHub compare of target branch -> merge commit returns exact `identical` with zero ahead/behind counts.
9. The target branch is re-read after the compare and its exact SHA matches the merge commit.

## Human checkpoint boundary

Promotion pull requests are prepared only for declared engineering-stage checkpoints on `develop` or release checkpoints on `main`. The develop checkpoint is bounded to one stage and uses ai/integration directly; the owner-verified source SHA is part of the PR evidence. Main release checkpoints may continue to use the snapshot artifact.

Aegis may create and verify the artifact, but never approves or merges protected branches. After a human-controlled merge, this workflow verifies the exact merge and synchronizes lifecycle state; it does not repair the protected branch.

See `docs/governance/promotion-checkpoints.md` for the promotion cadence.

## Rules

- Never approve or merge a pull request.
- Never force-push or modify a protected branch.
- Do not treat an open or merely mergeable pull request as merged.
- Do not advance the lifecycle when the target branch compare is not exact `identical` or the post-compare target SHA differs.
- Require traceability and lifecycle transition mutation evidence to report read-after-write verification before returning `Verified`.
- Optionally emit canonical `promotion-sync` evidence with `--canonical-evidence-output`; this evidence is observational and never authorization.
- Record only non-secret promotion evidence on the work item.
- Use the work-item provider's optimistic transition so concurrent lifecycle changes fail safely.

## Exit states

### Verified

The promotion merge is confirmed and the work item transitions integration -> done.

### Not merged

The promotion pull request is still open or has not actually merged. No work-item mutation occurs.

### Error

The promotion identity, target protection, merge commit, exact target comparison, or post-compare target identity cannot be verified.

## Implementation

The executable boundary is tools/promotion_sync.py.

The GitHub adapter is read-only for Git data and pull requests. The only mutation in the workflow is the deliberate work-item traceability/state update through the configured WorkItemProvider.
