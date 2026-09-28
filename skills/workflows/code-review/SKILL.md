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

Classify findings by impact. A review is evidence-based; do not invent defects that cannot be supported by the code, configuration, tests, or documented constraints.


## Pull-request handoff

After project quality gates move a work item to \`review\`, the delivery bridge can create or reuse the pull request and attach its traceability:

    python3 tools/delivery.py create OWNER/REPO 60 ai/feature/60-task ai/integration "feat: implement task" --body "Closes #60."

A successful create operation does not merge the pull request and leaves the work item in \`review\`.

After the pull request has actually merged into the explicit integration branch, synchronize the work item:

    python3 tools/delivery.py sync-merge OWNER/REPO 60 123 ai/feature/60-task ai/integration

Only a verified merged PR advances \`review -> integration\`.
