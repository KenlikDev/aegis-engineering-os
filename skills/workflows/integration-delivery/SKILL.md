---
name: integration-delivery
description: Compose task pull-request preparation, exact-SHA validation, and the controlled ai/integration merge into one auditable delivery operation.
---

# Integration Delivery

## Objective

Move one reviewed work item into ai/integration through one explicit, verified sequence.

## Sequence

1. Require the work item to be in review.
2. Create or reuse the task pull request targeting ai/integration.
3. Verify the pull request head and base.
4. Require successful Aegis Validation for the exact current task head SHA.
5. Delegate the merge to the controlled integration merge boundary.
6. Bind the merge to the same validated task-head SHA.
7. Require successful Aegis Validation for the exact resulting merge commit SHA.
8. Verify the resulting merge and lifecycle state.
9. Optionally emit canonical `integration-delivery` evidence with `--canonical-evidence-output`.

## Rules

- The target is always ai/integration.
- develop and main are never valid targets.
- Do not merge a draft pull request.
- Do not continue without exact-head validation evidence.
- Do not mark the work item `integration` until the exact merge commit has passed Aegis Validation.
- Do not accept a PR head change after validation.
- Keep the work-item transition optimistic and read-after-write verified.
- Keep merge approval and protected release promotion outside this workflow.
- Canonical integration-delivery evidence is an observation of an already completed composition; it is not validation authorization.

## Implementation

The executable composition boundary is tools/integration_delivery.py.

The lower-level boundaries remain independently testable:

- tools/delivery.py;
- tools/integration_merge.py;
- tools/promotion_readiness.py.
