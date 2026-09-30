# Human Promotion Checkpoints

## Purpose

Aegis may autonomously develop and integrate engineering changes through `ai/integration`. The protected branches `develop` and `main` remain human-controlled boundaries.

This document defines when Aegis prepares a promotion pull request for human review so protected-branch promotion remains deliberate, bounded, and auditable.

## Checkpoint model

### Engineering work

Individual work items may be implemented, verified, reviewed, and merged into `ai/integration` through the existing autonomous integration workflow.

A small implementation fix, test-only correction, refactoring, CI repair, or security hardening does not automatically create a `develop` promotion pull request.

The purpose of `ai/integration` is to absorb verified engineering work while the next protected-branch checkpoint is being prepared.

### Develop promotion checkpoint

Aegis prepares a promotion pull request to `develop` only when a declared engineering stage is complete.

A stage is complete for promotion when:

1. all work items included in the stage have reached their intended terminal engineering state;
2. the current `ai/integration` tree has been reviewed as a coherent stage rather than as a collection of unrelated changes;
3. the applicable implementation, testing, security, architecture, and documentation checks have passed;
4. canonical provenance and lifecycle evidence is internally consistent;
5. the exact current `ai/integration` SHA has a successful Aegis Validation run;
6. promotion readiness confirms the exact protected target state and ancestry;
7. a deterministic promotion snapshot is created from the exact source and target SHAs;
8. the resulting promotion pull request contains a bounded description of the stage and its exact source/target identities.

Aegis does not merge, approve, or otherwise authorize the resulting `develop` pull request.

The human reviewer makes the protected-branch decision from the bounded promotion artifact, the exact diff, the validation evidence, and the documented scope.

### Develop merge completion

After the owner merges the promotion pull request:

1. Aegis identifies the exact merge commit SHA;
2. Aegis verifies that `develop` is still at that exact merge SHA after the compare operation;
3. Aegis verifies the corresponding post-merge Aegis Validation result when the workflow path requires it;
4. Aegis may synchronize the associated work-item lifecycle using read-after-write verification;
5. Aegis does not perform any corrective write to `develop` automatically.

A failed post-merge verification is an observed failure, not permission for Aegis to modify the protected branch.

### Main release checkpoint

Aegis does not create a `main` promotion for every `develop` merge.

A `main` promotion pull request is prepared only for a release candidate or another explicitly declared release checkpoint after the relevant `develop` state has completed the required validation and release-readiness checks.

The `main` promotion follows the same human-controlled rule: Aegis prepares and verifies the promotion artifact but never approves or merges the protected branch.

## Cadence rule

There is no fixed number of engineering merges between protected-branch checkpoints.

The unit of promotion is the declared engineering stage, not the number of commits or issues. Aegis must not manufacture a stage solely to justify a promotion, and it must not silently accumulate unrelated unfinished work into one promotion.

A critical security, data-integrity, governance, or irreversible-operation change may justify an earlier dedicated checkpoint even when the surrounding stage is smaller. Such a checkpoint must still be explicitly bounded and fully validated.

## Review package

Every human promotion checkpoint should expose:

- the exact source `ai/integration` SHA;
- the exact protected target SHA observed before preparation;
- the promotion snapshot branch and SHA;
- the promotion pull request identity;
- validation run identities and conclusions;
- relevant canonical evidence references;
- the included work-item scope;
- any residual uncertainty or known blockers.

The package is evidence for human review. It is not an authorization token and does not transfer protected-branch ownership to Aegis.

## Recovery

If the target branch changes while promotion is being prepared, Aegis fails closed and prepares a new checkpoint from fresh state.

If a published promotion snapshot later encounters a preparation or provider error, Aegis does not perform an unsafe compare-then-delete cleanup. A valid snapshot is retained for idempotent retry; a missing or changed snapshot is treated as a recovery boundary.

## Non-goals

This policy does not:

- grant Aegis write or merge authority over `develop` or `main`;
- replace GitHub branch protection;
- convert validation success into product or release approval;
- require human review of every `ai/integration` commit;
- define product scope or acceptance criteria.
