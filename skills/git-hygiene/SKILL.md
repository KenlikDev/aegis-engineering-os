---
name: git-hygiene
description: Maintain clean, reviewable Git history for autonomous engineering work.
---

# Git Hygiene

## Branching

Use task branches such as:
- ai/feature/name
- ai/fix/name
- ai/refactor/name
- ai/chore/name

Shared integration branch:
- ai/integration

Never work directly on develop or main.

## Commits

A commit represents one coherent logical change.

Use Conventional Commits:
- feat:
- fix:
- refactor:
- test:
- docs:
- build:
- ci:
- chore:

Commit subjects are concise and written in English.

## Before commit

1. Run applicable checks.
2. Inspect git status.
3. Inspect the complete diff.
4. Remove unrelated modifications.
5. Check for secrets.
6. Confirm the commit message matches the actual change.

## Correcting mistakes

If a bad commit has not been pushed:
- prefer commit --amend for the latest local commit;
- use interactive rebase or fixup/squash when multiple local commits need cleanup;
- avoid avoidable corrective-commit noise.

If a commit has been pushed to a shared branch, prefer a new corrective commit unless history rewriting is explicitly allowed.

## Push policy

Do not push every small change.

Push at:
- verified logical milestones;
- safe recovery checkpoints for long-running work;
- PR creation or meaningful PR updates;
- explicit user-requested checkpoints.

Never push known-broken code merely to show progress.
