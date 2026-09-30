# Promotion Architecture

## Purpose

Aegis separates promotion preparation from protected-branch ownership.

The normal autonomous path ends at ai/integration. Promotion into develop or main is prepared as an explicit artifact and remains subject to the target branch policy.

## Readiness gate

tools/promotion_readiness.py is read-only.

Before any promotion write, Aegis verifies:

- the source is exactly ai/integration;
- the target is exactly develop or main;
- both branches are protected;
- the current source and target SHAs are captured;
- the source has successful Aegis Validation evidence for that exact source SHA; an exact integration push run is preferred, while a successful merged-PR validation may be accepted only when its actual merge commit equals the current source SHA;
- the source contains a positive promotable delta beyond the target; `ahead` is the normal ancestry shape, while `diverged` is expected after squash-based human promotion;
- optional expected SHAs still match the fresh state.

A readiness result is evidence, not permission to merge.

When requested with `--evidence-output`, the result is also adapted into the canonical provider-neutral provenance envelope. The specialized promotion-readiness JSON remains unchanged; the adapter preserves the exact source revision, target state, comparison, validation evidence type, blockers, and any uncertainty such as merged-pull-request CI fallback.

The observation timestamp is captured immediately before the provider assessment and normalized to UTC by the evidence contract.

## Snapshot preparation

tools/promotion_snapshot.py is the write boundary.

The operation is intentionally conservative:

1. run the readiness gate;
2. capture the exact source and protected target commit snapshots returned by that readiness observation;
3. verify that the source contains a positive promotable delta beyond the target; an ancestry `diverged` result is allowed after squash-based human promotion;
4. create one immutable snapshot commit with:
   - first parent = exact protected target SHA;
   - second parent = exact validated ai/integration SHA;
   - tree = exact tree of that validated source commit;
5. reread both source and protected target branches and require their SHAs to remain equal to the validated readiness snapshot;
6. create the short-lived branch ai/<work-item>-<target>-promotion directly at the snapshot commit SHA;
7. verify the branch commit, parents, and tree;
8. create or reuse one open pull request into the selected target;
9. return structured metadata without credentials.

The branch is never intentionally published first at the protected target SHA. A source or target change during preparation therefore fails closed before the promotion branch is published. Once a new promotion branch is published, later pull-request or verification failures never trigger automatic branch deletion because the GitHub delete-reference API has no expected-SHA compare-and-delete condition. A valid newly published snapshot branch is retained for safe idempotent retry; a missing or changed branch is treated as an explicit recovery boundary and Aegis never overwrites or deletes it automatically. A snapshot commit is bound to the exact source revision for which promotion readiness verified Aegis Validation.


The resulting commit represents the verified integration state as a target-based promotion artifact. Aegis does not resolve protected-target merge conflicts; the exact target/source diff remains part of the human promotion review.

## Idempotency

The promotion branch name is deterministic:

ai/<work-item>-develop-promotion
ai/<work-item>-main-promotion

When the branch already exists, its commit must exactly match the expected target parent, integration parent, and integration tree. A mismatch is a hard failure rather than an attempt to repair or overwrite the branch.

Open pull requests are searched by exact repository owner, head branch, and base branch. More than one matching open pull request is a hard failure.

## Pull-request repository origin

Promotion synchronization requires the promotion PR head and base repository identities to equal the configured repository. The repository-origin check is performed before protected-target synchronization and is preserved in canonical `promotion-sync` evidence.

This is separate from branch-name, commit-SHA, target-protection, and lifecycle verification. A matching branch name or commit SHA alone is not treated as proof that the PR originates from the configured repository.

## Safety boundary

The snapshot tool never:

- writes directly to develop or main;
- force-pushes;
- resolves merge conflicts;
- approves pull requests;
- merges pull requests;
- changes branch protection;
- stores or emits GitHub credentials.

Promotion branch writes are followed by read-back verification.

A target that is strictly behind ai/integration is blocked automatically because the source does not contain the full target history. A diverged target is allowed when the source has a positive promotable delta; this is expected after squash-based human promotion. Aegis does not reconcile the protected branch automatically, and the exact target/source diff remains a human review boundary.

## GitHub API contract

The implementation uses the versioned GitHub REST API with explicit API version 2026-03-10.

The Git database commit API accepts multiple parent SHAs, which is used to model the snapshot commit. The pull-request API is used only to create or inspect the prepared promotion artifact.

## Human promotion checkpoints

The autonomous engineering boundary ends at `ai/integration`. Aegis prepares a promotion pull request for `develop` only after a declared engineering stage has completed its applicable implementation, testing, security, architecture, documentation, provenance, and exact-SHA validation gates.

The unit of promotion is the stage, not the number of commits or issues. Unrelated unfinished work is not silently accumulated into a protected-branch promotion.

The resulting `develop` pull request is a human decision boundary. Aegis creates and verifies the promotion artifact but never approves or merges the protected branch. After a human merge, Aegis verifies the exact merge commit, the protected target read-back, and the applicable post-merge validation before lifecycle synchronization.

Main promotion is prepared only for a release candidate or another explicitly declared release checkpoint after the required develop validation and release-readiness evidence is complete.

The detailed cadence is defined in `docs/governance/promotion-checkpoints.md`.

## Lifecycle

The overall delivery path is:

work item -> task branch -> OpenHands -> verification -> quality gates
-> review -> task PR -> ai/integration
-> promotion readiness -> promotion snapshot PR
-> owner-controlled promotion -> develop/main

The final protected-branch merge remains outside the autonomous delivery boundary.

## Promotion synchronization

A promotion pull request is owner-controlled. tools/promotion_sync.py is the post-merge synchronization boundary.

The operation requires the work item to be in integration, verifies the deterministic promotion branch and protected target, verifies that both the promotion PR head repository and base repository equal the configured repository, requires an actual closed-and-merged PR with a merge commit SHA, and compares the target branch against that merge commit with an exact `identical` result. It then re-reads the protected target and requires its SHA to equal the merge commit. Only after both traceability and integration -> done lifecycle mutations report read-after-write verification does it return `status=verified`.

Open or unmerged promotion PRs are non-mutating. The synchronizer never approves, merges, force-pushes, or changes protected branches.

The synchronized result can also be serialized as canonical `promotion-sync` evidence. A verified record binds the human-controlled target branch, exact promotion merge revision, protected target identity, pull-request identity, traceability verification, and integration -> done lifecycle verification. A `not-merged` result remains canonical `unknown`. This evidence is observational and does not authorize or perform promotion.


## Validation evidence types

Promotion readiness distinguishes two valid CI evidence forms.

A branch-push validation has head_sha equal to the current ai/integration SHA. This is the preferred evidence because the workflow run directly represents the integration branch commit.

A merged-pull-request validation may be used when GitHub does not expose an equivalent push run. In that case Aegis verifies the successful workflow run, locates the closed merged pull request by the workflow head branch, requires base ai/integration, requires the pull-request head SHA to match the workflow head SHA, and requires merge_commit_sha to equal the current ai/integration SHA.

The workflow evidence therefore records both the workflow head SHA and the commit SHA actually validated by the merged event.
