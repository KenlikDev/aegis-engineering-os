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
3. The pull-request head matches ai/<work-item>-<target>-promotion.
4. The pull-request base matches the selected protected target.
5. The pull request is closed and actually merged.
6. A merge commit SHA is present.
7. The target branch is still protected.
8. The target branch contains the promotion merge commit.

## Rules

- Never approve or merge a pull request.
- Never force-push or modify a protected branch.
- Do not treat an open or merely mergeable pull request as merged.
- Do not advance the lifecycle when the target branch does not contain the merge commit.
- Record only non-secret promotion evidence on the work item.
- Use the work-item provider's optimistic transition so concurrent lifecycle changes fail safely.

## Exit states

### Verified

The promotion merge is confirmed and the work item transitions integration -> done.

### Not merged

The promotion pull request is still open or has not actually merged. No work-item mutation occurs.

### Error

The promotion identity, target protection, merge commit, or target ancestry cannot be verified.

## Implementation

The executable boundary is tools/promotion_sync.py.

The GitHub adapter is read-only for Git data and pull requests. The only mutation in the workflow is the deliberate work-item traceability/state update through the configured WorkItemProvider.
