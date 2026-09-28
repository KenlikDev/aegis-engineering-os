---
name: release-preparation
description: Prepare and verify a production release using explicit version, changelog, CI, and protected-branch evidence without publishing release artifacts autonomously.
---

# Release Preparation

## Objective

Determine whether the protected release branch is ready for a human-controlled release decision.

## Entry conditions

- implementation is already integrated into the release branch;
- the release target is explicitly identified as main;
- current repository state can be observed;
- required validation workflow results are available.

## Required evidence

1. Read the exact main commit SHA.
2. Verify main remains protected.
3. Verify a successful Aegis Validation run exists for that exact SHA.
4. Read VERSION, aegis-manifest.json, and skills/registry.json.
5. Verify all version values agree and use an accepted release version format.
6. Read CHANGELOG.md.
7. Require a populated heading for the current version.
8. Detect and report any non-empty Unreleased section as release-notes work still pending.

## Rules

- Read-only readiness tools must not create tags or releases.
- Never rewrite release history to make a release pass.
- Never silently bump the version during readiness evaluation.
- Treat release notes handling as explicit work.
- Record blockers exactly; do not weaken the gate to obtain a green result.

## Exit states

### Ready

All required evidence is present and no blockers remain.

### Blocked

One or more required evidence checks failed.

### Error

Current state could not be evaluated safely.

## Implementation

The executable read-only gate is tools/release_readiness.py.

It uses stable exit codes:

- 0 — ready;
- 2 — blocked;
- 1 — evaluation/configuration error.

The tool never creates tags, GitHub Releases, branches, commits, or pull requests.
