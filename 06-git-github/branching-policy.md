# GitHub Branching and Integration Policy

## Branch model

Autonomous task branches:

ai/feature/*
ai/fix/*
ai/refactor/*
ai/chore/*
        -> ai/integration
        -> develop
        -> main

Short-lived promotion branches are created from the promotion target so squash-only promotion does not replay the shared integration history:

ai/<issue>-develop-promotion -> develop
ai/<issue>-main-promotion -> main

Promotion branches are owner-controlled delivery mechanisms and are not autonomous task branches.

## Ownership

- task ai/* branches: autonomous engineering workspace;
- ai/integration: AI staging and integration branch;
- promotion branches: prepared by Aegis, merged only according to the target branch policy;
- develop: human-controlled development branch;
- main: human-controlled release branch.

## Protection intent

develop and main should require pull requests, successful required checks, and human approval according to repository policy.

ai/integration should require successful automated quality gates before changes are accepted. Human approval can remain optional if the owner intentionally chooses that autonomy level.

## Commit and push frequency

A clean local history is more important than frequent remote pushes.

Use local commits to organize coherent work. Push clean, verified checkpoints rather than every small change.

For long-running work, a clean recovery checkpoint may be pushed when useful, but it must not become a stream of noisy WIP commits.

## Merge strategy

Squash merge task branches into ai/integration when that improves history clarity.

For promotion branches, create a clean snapshot from the target branch containing only the verified delta from ai/integration. Use squash merge into develop or main according to the target branch policy.

The exact strategy can be revised after real-world validation.


## Pull-request delivery boundary

The executable delivery boundary is \`tools/delivery.py\`.

The allowed autonomous sequence is:

\`review -> PR created/verified -> integration\`

The delivery layer may create or reuse a PR from an \`ai/*\` task branch into an explicit \`ai/*\` integration branch. It must not approve, merge, or promote into \`develop\` or \`main\`.

After a PR is actually merged, \`sync-merge\` verifies the PR source branch and target branch before advancing the authoritative work item from \`review\` to \`integration\`.

The bridge never treats \`mergeable=true\` or a clean mergeability state as equivalent to an actual merge.


## Promotion readiness

The read-only promotion verifier is \`tools/promotion_readiness.py\`.

It evaluates \`ai/integration -> develop\` or \`ai/integration -> main\` using fresh GitHub state. The target must be explicitly selected and protected; \`ai/integration\` must also remain protected.

The verifier records the exact source and target SHAs, compare divergence, changed-file count, and the result of the required \`Aegis Validation\` workflow for the exact source SHA.

Promotion is blocked when the source is behind the target, contains no delta, the exact source SHA has no successful \`Aegis Validation\`, the protected-state assumptions are false, or the caller supplied expected SHAs that no longer match.

The verifier is read-only. It does not create promotion branches, modify branch protection, merge pull requests, or change \`develop\`/\`main\`.

## Integration validation trigger
The concurrency group includes the triggering event and pull-request number where available. This prevents a merged pull-request validation from cancelling the branch push validation that records the exact integration SHA.


Task pull requests are validated on opened, synchronized, and reopened events. The validation workflow also handles merged pull requests explicitly with the closed activity and a merged == true condition.

For a merge into ai/integration, the closed-PR path checks out the pull request's actual merge commit SHA. This is a second validation path for the resulting integration state, independent of whether the repository emits an observable push-triggered run.

The workflow keeps contents: read and does not use pull_request_target. No credentials with write access are introduced for post-merge verification.
