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
- the source has a successful Aegis Validation run for that exact SHA;
- the source is ahead of the target and not behind it;
- optional expected SHAs still match the fresh state.

A readiness result is evidence, not permission to merge.

## Snapshot preparation

tools/promotion_snapshot.py is the write boundary.

The operation is intentionally conservative:

1. run the readiness gate;
2. reread the source and target commit objects;
3. verify that target is an ancestor of the source;
4. create the short-lived branch ai/<work-item>-<target>-promotion from the exact target SHA;
5. create one snapshot commit with:
   - first parent = exact target SHA;
   - second parent = exact ai/integration SHA;
   - tree = exact ai/integration tree;
6. move the promotion branch forward without force;
7. verify the branch commit, parents, and tree;
8. verify that the target branch did not change while preparing the snapshot;
9. create or reuse one open pull request into the selected target;
10. return structured metadata without credentials.

The resulting commit represents the verified integration state as a target-based promotion artifact. Because the target is required to be an ancestor, no merge conflict needs to be resolved by Aegis.

## Idempotency

The promotion branch name is deterministic:

ai/<work-item>-develop-promotion
ai/<work-item>-main-promotion

When the branch already exists, its commit must exactly match the expected target parent, integration parent, and integration tree. A mismatch is a hard failure rather than an attempt to repair or overwrite the branch.

Open pull requests are searched by exact repository owner, head branch, and base branch. More than one matching open pull request is a hard failure.

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

A target that is behind or diverged from ai/integration is intentionally not auto-reconciled. The owner must reconcile that protected branch through the normal protected-branch workflow before another snapshot can be prepared.

## GitHub API contract

The implementation uses the versioned GitHub REST API with explicit API version 2026-03-10.

The Git database commit API accepts multiple parent SHAs, which is used to model the snapshot commit. The pull-request API is used only to create or inspect the prepared promotion artifact.

## Lifecycle

The overall delivery path is:

work item -> task branch -> OpenHands -> verification -> quality gates
-> review -> task PR -> ai/integration
-> promotion readiness -> promotion snapshot PR
-> owner-controlled promotion -> develop/main

The final protected-branch merge remains outside the autonomous delivery boundary.
