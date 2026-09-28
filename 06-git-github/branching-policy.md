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
