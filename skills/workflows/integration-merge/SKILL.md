---
name: integration-merge
description: Merge one verified Aegis task pull request into the protected ai/integration branch using an exact head SHA and squash merge.
---

# Integration Merge

## Objective

Complete the autonomous task delivery boundary by merging a verified task pull request into ai/integration.

## Entry conditions

- work item is in review;
- pull request number is explicit;
- pull request head is an Aegis task branch for the same work item;
- pull request base is ai/integration;
- ai/integration remains protected.

## Required checks

1. Read the current ai/integration branch state.
2. Read the pull request.
3. Reject draft pull requests.
4. Reject pull requests whose mergeable_state is not clean.
5. Use the exact current pull-request head SHA as the merge precondition.
6. Merge with squash only.
7. Read the pull request again.
8. Require the pull request to be closed and actually merged.
9. Require a merge commit SHA.
10. Require successful Aegis Validation for the exact merge commit SHA.
11. Verify the merge commit is contained in the current ai/integration history.
12. Attach safe merge evidence to the work item.
13. Advance review -> integration only after the post-merge validation and ancestry checks pass.

## Idempotency

An already merged pull request is not merged again. The synchronizer still requires successful validation for its exact merge commit and verifies that commit remains in ai/integration history before completing the lifecycle transition.

## Safety rules

- Never target develop or main.
- Never force-push.
- Never approve a review.
- Never bypass branch protection.
- Never treat mergeable=true as proof that a merge occurred.
- Stop on ambiguous or inconsistent GitHub responses.

## Implementation

The executable boundary is tools/integration_merge.py.

Only the explicitly permitted ai/integration merge is write-capable. Protected promotion and release branches remain outside this autonomous merge boundary.
