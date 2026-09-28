# Integration Delivery Architecture

## Purpose

Integration delivery is the autonomous boundary between a reviewed task and ai/integration.

It composes three independently testable capabilities:

1. pull-request creation/reuse;
2. exact-SHA validation evidence;
3. controlled ai/integration merge.

The composition does not extend the authority of any component beyond its existing boundary.

## Sequence

review
-> create/reuse task PR
-> read current PR head
-> require successful Aegis Validation for that exact head SHA
-> re-read PR during merge
-> require the head SHA to remain unchanged
-> squash merge with the exact validated SHA
-> verify merged PR and merge commit
-> advance work item review -> integration

## Race safety

Validation evidence is bound to the exact PR head SHA.

The integration merge operation accepts an optional expected_head_sha. When supplied, it fails closed if the current PR head differs from the validated SHA.

This prevents a new commit pushed after validation from being merged using stale validation evidence.

## Safety boundary

The controller only accepts ai/integration as its target.

It never:

- targets develop or main;
- force-pushes;
- approves pull requests;
- bypasses branch protection;
- merges a draft pull request;
- merges without successful exact-head Aegis Validation.

Already-merged pull requests are treated as an idempotent recovery case: the controller skips a new merge attempt and verifies the existing merge through the lower-level integration synchronization boundary.

## Provider boundary

The composition uses provider-neutral interfaces:

PullRequestProvider
IntegrationMergeProvider
ValidationProvider
WorkItemProvider

GitHub-specific implementations are selected only by the CLI adapter layer.

## Failure behavior

No successful exact-head validation:
- do not merge;
- leave the work item in review.

PR head changed after validation:
- do not merge;
- leave the work item in review.

PR is draft, not clean, or targets the wrong branch:
- do not merge;
- report the condition.

Successful verified merge:
- attach traceability;
- advance review -> integration;
- verify the resulting work-item state.

## Lifecycle position

work item
-> execution
-> verification
-> quality gates
-> review
-> integration delivery
-> ai/integration
-> promotion readiness
-> promotion snapshot
-> owner-controlled promotion
-> main
-> release readiness
-> owner-controlled release publication
