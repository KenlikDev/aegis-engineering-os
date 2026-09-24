# GitHub Branch Protection

GitHub must enforce repository boundaries in addition to agent instructions.

## develop

Recommended:
- require pull requests;
- require at least one approval;
- require the Aegis Validation check;
- require conversation resolution;
- dismiss stale approvals when the diff changes;
- block force pushes and branch deletion;
- do not allow bypassing the rules when practical.

## main

Recommended:
- require pull requests;
- require at least one approval;
- require the Aegis Validation check;
- require conversation resolution;
- dismiss stale approvals when the diff changes;
- block force pushes and branch deletion;
- do not allow bypassing the rules when practical.

## ai/integration

Recommended:
- require the Aegis Validation check;
- block force pushes and deletion.

Human approval can remain optional if autonomous staging is desired.

## Limitation

The current GitHub integration used for this setup can inspect repository and branch state but cannot create or edit branch-protection rules. The repository owner must configure these settings in GitHub.

See the official GitHub documentation for branch protection and rulesets.
