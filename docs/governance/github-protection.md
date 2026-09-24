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
