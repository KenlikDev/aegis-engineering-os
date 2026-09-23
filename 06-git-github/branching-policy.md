# GitHub Branching and Integration Policy

## Branch model

ai/feature/*, ai/fix/*, and ai/chore/*
        -> ai/integration
        -> develop
        -> main

## Ownership

- ai/*: autonomous engineering workspace.
- ai/integration: AI staging and integration branch.
- develop: human-controlled development branch.
- main: human-controlled release branch.

## Protection intent

develop and main should require pull requests, successful required checks, and human approval according to repository policy.

ai/integration should require successful automated quality gates before changes are accepted. Human approval can remain optional if the owner intentionally chooses that autonomy level.

## Commit and push frequency

A clean local history is more important than frequent remote pushes.

Use local commits to organize coherent work. Push clean, verified checkpoints rather than every small change.

For long-running work, a clean recovery checkpoint may be pushed when useful, but it must not become a stream of noisy WIP commits.

## Merge strategy

Squash merge task branches into ai/integration when that improves history clarity. Preserve meaningful integration commits when they add useful context.

The exact strategy can be revised after real-world validation.
