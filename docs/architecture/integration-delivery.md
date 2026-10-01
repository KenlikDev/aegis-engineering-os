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
-> require successful Aegis Validation for the exact merge commit SHA
-> compare `ai/integration` against the merge commit and require `identical`
-> re-read `ai/integration` and require its SHA to equal the merge commit
-> advance work item review -> integration

## Race safety

Validation evidence is bound to the exact PR head SHA.

The integration merge operation requires `expected_head_sha` for every open pull request and a separate successful Aegis Validation observation for the resulting merge commit before lifecycle synchronization. GitHub pull-request data must also identify both `head.repo.full_name` and `base.repo.full_name`, and both must equal the configured repository. A fork-origin pull request is rejected even when its branch name and commit SHA match the expected Aegis values. It fails closed if the current PR head differs from the exact SHA supplied by the higher-level validation boundary. Already-merged pull requests may omit the pre-merge task-head SHA because no new merge mutation is performed, but they still require successful validation for the exact existing merge commit before lifecycle synchronization.

This prevents a new commit pushed after validation from being merged using stale validation evidence.

## Pull-request repository origin

Every PR consumed by integration delivery carries explicit `head.repo.full_name` and `base.repo.full_name` provenance. Both repository identities must equal the configured repository before a PR can participate in autonomous merge, lifecycle synchronization, or canonical verified evidence.

Canonical `integration-delivery` provenance preserves these origin fields so downstream consumers can distinguish repository ownership verification from branch-name and SHA validation. Missing or foreign origin data cannot be represented as verified evidence.

`not-merged` observations remain `unknown`; they do not claim successful repository-origin verification or a completed integration merge.

## Safety boundary

The controller only accepts ai/integration as its target.

It never:

- targets develop or main;
- force-pushes;
- approves pull requests;
- bypasses branch protection;
- merges a draft pull request;
- merges without successful exact-head Aegis Validation;
- synchronizes review -> integration without successful validation of the exact resulting merge commit.

Already-merged pull requests are treated as an idempotent recovery case: the controller skips a new merge attempt and verifies the existing merge through the lower-level integration synchronization boundary.

## Provider boundary

The composition uses provider-neutral interfaces:

PullRequestProvider
IntegrationMergeProvider
ValidationProvider
WorkItemProvider

GitHub-specific implementations are selected only by the CLI adapter layer.

## Failure behavior

No exact-head validation SHA for an open PR:
- do not merge;
- leave the work item in review.

Post-merge comparison is not `identical`:
- do not advance the work item lifecycle;
- do not report integration as verified.

PR head changed after validation:
- do not merge;
- leave the work item in review.

PR is draft, not clean, or targets the wrong branch:
- do not merge;
- report the condition.

Successful verified merge:
- require post-merge Aegis Validation for the exact merge commit SHA;
- verify traceability mutation evidence;
- verify lifecycle transition mutation evidence;
- attach traceability;
- advance review -> integration;
- verify the resulting work-item state;
- optionally emit canonical `integration-merge` evidence with `--canonical-evidence-output`.

An integration result is not reported as `verified` when either provider mutation is marked unverified. Canonicalization preserves the exact merge revision and any explicit validated head SHA; it does not create validation or authorization.

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
