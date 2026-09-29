# Release Readiness Architecture

## Purpose

Release readiness is a read-only evidence gate for the protected main branch.

It answers whether the repository has enough current evidence for a human-controlled release decision. It does not publish a release and does not change repository state.

## Required evidence

tools/release_readiness.py checks:

1. main is the explicit release target;
2. main is protected;
3. the current main SHA has a successful Aegis Validation run;
4. VERSION contains an accepted semantic release version;
5. VERSION matches aegis-manifest.json;
6. VERSION matches skills/registry.json;
7. CHANGELOG.md contains a populated section for the current version;
8. CHANGELOG.md has no non-empty Unreleased section still awaiting release handling.

The tool reports the exact observed SHA, validation evidence, version values, changelog state, and blockers.

With `--evidence-output`, the same assessment can be persisted through the canonical evidence provenance adapter without changing the existing stdout schema.

## Provider boundary

The orchestration contract is provider-neutral:

ReleaseReadinessProvider
-> branch state
-> validation state
-> repository file contents

GitHub-specific REST behavior is isolated in GitHubReleaseReadinessProvider.

Release readiness does not require a write-capable integration. Its GitHub adapter explicitly rejects payload-bearing transport calls.

## Safety boundary

The tool never:

- creates or moves Git refs;
- creates tags;
- creates GitHub Releases;
- creates pull requests;
- modifies files;
- changes protected branches;
- rewrites version metadata;
- edits release notes.

A blocked readiness result is an expected state, not an execution failure. The owner or a separate release-preparation task must resolve the reported blockers.

## Exit codes

- 0 — ready;
- 2 — blocked by observed release-readiness conditions;
- 1 — evaluation or configuration error.

The result is JSON so it can be archived or consumed by a higher-level release workflow without exposing credentials.

The optional canonical evidence artifact records the exact main revision and validation provenance. The observation timestamp is captured immediately before the provider assessment.

## Overall delivery lifecycle

work item
-> task branch
-> OpenHands execution
-> verification
-> quality gates
-> review
-> ai/integration
-> promotion readiness
-> promotion snapshot PR
-> owner-controlled promotion
-> main
-> release readiness
-> owner-controlled release publication

Release publication remains outside the autonomous Aegis write boundary.


## GitHub credential destination

The GitHub release-readiness adapter sends bearer credentials only to the exact `https://api.github.com` origin. Arbitrary HTTPS hosts, non-root paths, URL credentials, queries, and fragments are rejected.
