# GitHub Branch Protection

GitHub rulesets are the enforcement layer around the Aegis branch policy. Documentation must describe the live configuration, not an assumed or historical configuration.

## Current repository configuration

The repository is currently configured as follows.

### main

- pull request required;
- required approving reviews: 0;
- required status check: Validate Aegis;
- strict required status checks: enabled;
- conversation resolution: required;
- force pushes blocked;
- branch deletion blocked;
- bypass actors: none;
- allowed merge method: squash only;
- linear history: required.

### develop

- pull request required;
- required approving reviews: 0;
- required status check: Validate Aegis;
- strict required status checks: enabled;
- conversation resolution: required;
- force pushes blocked;
- branch deletion blocked;
- bypass actors: none;
- allowed merge method: squash only;
- linear history: required.

### ai/integration

- pull request required;
- required approving reviews: 0;
- required status check: Validate Aegis;
- strict required status checks: enabled;
- conversation resolution: not required;
- force pushes blocked;
- branch deletion blocked;
- bypass actors: none;
- allowed merge method: squash only;
- linear history: required.

## Promotion ownership

The protected-branch merge authority remains human-controlled even when Aegis is allowed to prepare promotion artifacts. Aegis may create and verify a deterministic promotion pull request, but it must not approve or merge `develop` or `main`.

A develop promotion pull request is a bounded engineering-stage checkpoint, not a mirror of every `ai/integration` change. Main promotion is reserved for release-candidate or explicitly declared release checkpoints.

See [Human Promotion Checkpoints](promotion-checkpoints.md) for the operational cadence.

## Approval model

The current repository uses one GitHub account for the owner and autonomous agent. Therefore the rulesets do not require an approving review.

The human-controlled nature of develop and main is enforced through the promotion workflow and branch protection, while additional independent reviewers can be introduced later by changing the required approval count and reviewer rules.

Do not describe a future reviewer configuration as if it were the current live configuration.

## Merge model

Aegis uses squash-only merges for the protected branches.

The purpose is to keep integration history task-oriented: internal implementation commits remain available on the task branch, while the target branch receives one logical commit per merged pull request.

Linear history is required so merge commits do not become part of the protected-branch history.

## Verification rule

When this document is used to make a repository decision, Aegis must verify the live ruleset state first. This document is a policy description, not an authoritative copy of GitHub's current configuration.

## Limitation

The current GitHub integration used for this setup can inspect repository and ruleset state but cannot create or edit branch-protection rules through the available administration interface. The repository owner must change these settings in GitHub.

See the official GitHub documentation for branch protection and rulesets.


## Live ruleset audit

Before relying on this document for a repository decision, Aegis can inspect the live repository rulesets through the read-only audit boundary:

    GITHUB_TOKEN="$TOKEN" python3 tools/github_protection_audit.py OWNER/REPO

The default audit checks `main`, `develop`, and `ai/integration`. Use repeated `--branch` arguments for a narrower scope. The tool uses the repository ruleset API and requires credentials appropriate to the controls being inspected. Complete bypass-actor verification requires the returned `bypass_actors` field; GitHub may omit that field for callers without sufficient ruleset access. The audit preserves an omitted field as `null` rather than treating it as an empty bypass list. It fails closed when a requested branch has zero or multiple active branch rulesets, or when the returned ruleset schema is malformed. It performs no GitHub mutations.

To persist the observation as canonical provenance:

    GITHUB_TOKEN="$TOKEN" python3 tools/github_protection_audit.py OWNER/REPO \
      --canonical-evidence-output /tmp/github-ruleset-audit.json

The evidence records only the relevant protection controls and ruleset links; credentials are never included.
