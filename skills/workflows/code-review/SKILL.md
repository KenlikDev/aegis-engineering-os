---
name: code-review
description: Review a change as an independent reviewer and identify defects, risks, compatibility problems, and missing verification.
---

# Code Review

## Review order

1. Requirements and acceptance criteria.
2. Architecture and boundaries.
3. Correctness and edge cases.
4. Error handling and concurrency.
5. Security and privacy.
6. Performance risks.
7. Tests and regression coverage.
8. Version compatibility.
9. Documentation.
10. Scope and Git hygiene.
11. Mutation verification boundaries.
12. Exact revision/run identity and post-mutation read-back.
13. Live branch protection and authorization boundaries.

Classify findings by impact. A review is evidence-based; do not invent defects that cannot be supported by the code, configuration, tests, or documented constraints.


## Pull-request handoff

After project quality gates move a work item to \`review\`, the delivery bridge can create or reuse the pull request and attach its traceability:

    python3 tools/delivery.py create OWNER/REPO 60 ai/feature/60-task ai/integration "feat: implement task" --body "Closes #60."

A successful create operation does not merge the pull request and leaves the work item in \`review\`.

After the pull request has actually merged into the explicit integration branch, synchronize the work item:

    python3 tools/delivery.py sync-merge OWNER/REPO 60 123 ai/feature/60-task ai/integration

Only a verified merged PR advances \`review -> integration\`.


## Full repository audit protocol

For a fresh-review audit, assume existing code may be wrong even when CI is green. Inspect the complete repository tree and inventory executable files, configuration, skills, tests, workflows, templates, and architecture documents.

For every material workflow boundary, trace input validation through mutation, read-after-write verification, returned status, canonical evidence, and downstream consumers. Search for places where `verified`, `ready`, `passed`, `completed`, `active`, or `authorized` are assigned without a directly corresponding proof condition. Verify that `unknown`, `pending`, `blocked`, and `failed` remain distinguishable.

For GitHub delivery, record exact PR head SHA, exact validation run head SHA, exact merge SHA, exact integration target SHA, and post-merge workflow SHA separately. Never substitute PR validation for post-merge validation. Autonomous merges are valid only on explicitly authorized integration branches; protected promotion remains human-controlled.

Review security as implementation behavior: redirect policy, URL schemes, subprocess invocation, shell use, credential handling, redaction, path confinement, output bounds, duplicate JSON keys, and sensitive-field scanners all require concrete checks and regression coverage.

Cross-check canonical documentation, skills, registry wiring, CLI flags, tests, and implementation so no layer advertises a capability that another layer does not enforce.
