---
name: ci-remediation
description: Diagnose failed CI runs from observable workflow, job, step, and log evidence without mutating CI state.
---

# CI Remediation

## Objective

Turn a failed CI run into a bounded, evidence-based diagnosis that can be handed to engineering execution.

## Required evidence

Collect:

- the exact workflow run identity;
- repository identity;
- workflow status and conclusion;
- failed jobs;
- failed step names when available;
- bounded job logs.

## Classification

The executable classifier recognizes only deterministic high-confidence signatures:

- CI permission failures;
- timeouts;
- security-review failures;
- repository structural validation failures;
- Python source syntax failures;
- test failures;
- bootstrap failures.

Unknown signatures are reported as inconclusive rather than guessed.

## Safety

- Read-only only.
- Never rerun, cancel, retry, approve, merge, edit, or dispatch workflows.
- Never change repository files or Git refs.
- Redact credential-like values before evidence serialization.
- Bound log evidence to a fixed size.
- Distinguish observed evidence from inferred root cause.

## Implementation

The executable boundary is tools/ci_diagnosis.py.

CLI forms:

    python3 tools/ci_diagnosis.py OWNER/REPO --run-id 123

or:

    python3 tools/ci_diagnosis.py OWNER/REPO --latest --workflow .github/workflows/validate.yml --branch ai/integration

Exit codes:

- 0 — healthy run or deterministic diagnosis completed;
- 2 — diagnosis is inconclusive;
- 1 — input/provider error.

The tool never performs a remediation mutation. A separate approved engineering workflow may use the diagnosis as input for corrective work.
