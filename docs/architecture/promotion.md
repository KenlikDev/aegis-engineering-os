# Promotion Architecture

## Purpose

Aegis separates promotion preparation from protected-branch ownership.

The normal autonomous path ends at ai/integration. Develop promotion is an explicit owner-gated pull request from the verified ai/integration branch. Main release promotion may use a separate snapshot artifact when the release process requires it.

## Readiness gate

tools/promotion_readiness.py is read-only.

Before any promotion write, Aegis verifies:

- the source is exactly ai/integration;
- the target is exactly develop or main;
- both branches are protected;
- the current source and target SHAs are captured;
- the source has successful Aegis Validation evidence for that exact source SHA; an exact integration push run is preferred, while a successful merged-PR validation may be accepted only when its actual merge commit equals the current source SHA;
- the source contains a positive promotable delta beyond the target, including at least one changed file; the GitHub compare relationship must also be internally consistent (`ahead`, `behind`, `diverged`, or `identical` must agree with their commit counts);
- optional expected SHAs still match the fresh state.

A readiness result is evidence, not permission to merge.

When requested with `--evidence-output`, the result is also adapted into the canonical provider-neutral provenance envelope. The specialized promotion-readiness JSON remains unchanged; the adapter preserves the exact source revision, target state, comparison, validation evidence type, blockers, and any uncertainty such as merged-pull-request CI fallback.

The observation timestamp is captured immediately before the provider assessment and normalized to UTC by the evidence contract.

## Develop promotion

tools/develop_promotion.py is the write boundary for develop promotion.

Successful develop preparation can optionally be serialized as canonical `develop-promotion` evidence with `--evidence-output`. The evidence binds the work item, owner-verified source SHA, protected target SHA, direct pull-request identity (including repository origin), and exact-source Aegis Validation result. The artifact is observational and does not authorize or merge the protected branch.

The operation is intentionally conservative:

1. require an explicit owner-verified source SHA as an operator-provided precondition;
2. require the authoritative work item to be in the `integration` lifecycle state;
3. run the read-only readiness gate with expected_source_sha set to that exact SHA;
4. capture the exact current source and protected target SHAs;
5. require the source to remain exactly equal to the owner-verified SHA before any pull-request write;
6. search for at most one existing open PR from ai/integration to develop;
7. re-run the exact-SHA readiness check immediately before any PR write;
8. create or reuse the direct pull request only when its head SHA, base, target protection, and verification marker match the owner-verified SHA;
9. record the verified SHA in the PR body;
10. reread the pull request and return structured metadata without credentials.

No temporary develop branch or synthetic merge commit is created. If ai/integration advances after the owner verification, the expected-source check fails closed and the develop PR is not created or reused as a verified checkpoint. While a develop PR remains open, the required `Validate Aegis` workflow also fails closed whenever the direct PR head SHA differs from its recorded owner-verified source SHA, so branch advancement invalidates the protected-branch check path.

tools/promotion_snapshot.py remains the write boundary for the main release-promotion snapshot flow. It rejects develop targets.

## Idempotency

Develop promotion has no synthetic branch. Its idempotent identity is the exact pair ai/integration -> develop plus the owner-verified source SHA.

Main snapshot promotion retains its deterministic branch:

ai/<work-item>-main-promotion

When the branch already exists, its commit must exactly match the expected target parent, integration parent, and integration tree. A mismatch is a hard failure rather than an attempt to repair or overwrite the branch.

Open pull requests are searched by exact repository owner, head branch, and base branch. More than one matching open pull request is a hard failure. The selected pull request must also expose an exact valid head SHA equal to the verified promotion commit SHA; matching branch names alone are not sufficient provenance.

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

## Required-check enforcement

For a direct `ai/integration -> develop` pull request, `.github/workflows/validate.yml` executes `tools/validate_develop_promotion.py` before the ordinary validation suite. The gate is read-only and requires exactly one authoritative `Work item: #<id>` marker plus the exact pull-request head SHA matching the single `Verified source SHA` marker recorded by the owner-gated promotion tool. Other pull-request flows are outside this specialized check. Because the protected `develop` ruleset requires `Validate Aegis`, a drifted direct promotion PR fails its required validation rather than remaining ordinarily merge-eligible.

## Lifecycle

The overall delivery path is:

work item -> task branch -> OpenHands -> verification -> quality gates
-> review -> task PR -> ai/integration
-> owner verification -> direct develop PR
-> owner-controlled promotion -> develop
-> release checkpoint -> main

The final protected-branch merge remains outside the autonomous delivery boundary.

## Promotion synchronization

A promotion pull request is owner-controlled. tools/promotion_sync.py is the post-merge synchronization boundary.

The operation requires the work item to be in integration, verifies the develop PR head is ai/integration or the main PR head is the deterministic release-promotion branch, verifies that both the promotion PR head repository and base repository equal the configured repository, requires an actual closed-and-merged PR with a merge commit SHA, and compares the target branch against that merge commit with an exact `identical` result. It then re-reads the protected target and requires its SHA to equal the merge commit. Only after both traceability and integration -> done lifecycle mutations report read-after-write verification does it return `status=verified`.

For develop, the synchronizer also requires exactly one PR body Work item marker matching the synchronized work item, plus the owner-verification marker and PR head SHA to equal the owner-verified source SHA. If the identity markers are missing, duplicated, mismatched, or stale, synchronization fails closed. Open or unmerged promotion PRs are non-mutating. The synchronizer never approves, merges, force-pushes, or changes protected branches.

The synchronized result can also be serialized as canonical `promotion-sync` evidence. A verified record binds the human-controlled target branch, exact promotion merge revision, protected target identity, pull-request identity, traceability verification, and integration -> done lifecycle verification. A `not-merged` result remains canonical `unknown`. This evidence is observational and does not authorize or perform promotion.


## Validation evidence types

Promotion readiness distinguishes two valid CI evidence forms.

A branch-push validation has head_sha equal to the current ai/integration SHA. This is the preferred evidence because the workflow run directly represents the integration branch commit.

A merged-pull-request validation may be used when GitHub does not expose an equivalent push run. In that case Aegis verifies the successful workflow run, locates the closed merged pull request by the workflow head branch, requires base ai/integration, requires the pull-request head SHA to match the workflow head SHA, and requires merge_commit_sha to equal the current ai/integration SHA.

The workflow evidence therefore records both the workflow head SHA and the commit SHA actually validated by the merged event.
