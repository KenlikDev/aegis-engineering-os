---
name: security-review
description: Perform a read-only security review of Aegis workflows and executable tooling, reporting deterministic findings without modifying the repository.
---

# Security Review

## Objective

Identify high-confidence security risks before integration without changing repository state.

## Scope

The executable review covers:

- GitHub Actions workflow trust boundaries;
- explicit permissions and broad write permissions;
- third-party action pinning;
- GitHub API versioning;
- high-risk subprocess execution;
- force-push and destructive Git reset patterns;
- direct hardcoded writes to protected main/develop refs;
- high-confidence credential material in reviewed source/config files.

## Severity

### High

A high finding blocks the review.

Examples:

- pull_request_target in the Aegis workflow set;
- missing explicit workflow permissions;
- unpinned third-party action;
- subprocess shell=True;
- force-push or force=True Git ref update;
- hardcoded direct writes to protected refs;
- GitHub API usage without the required version header;
- high-confidence credentials in source/config.

### Medium

A medium finding is reported but does not block by itself.

Example:

- explicit write permission that needs justification.

## Rules

- The review is read-only.
- Do not silently fix findings.
- Do not claim that the repository is secure in an absolute sense.
- Report only observable evidence and deterministic rule matches.
- Review output must not include credential values.
- The active skill registry is not modified by the review itself.

## Implementation

The executable boundary is tools/security_review.py.

Exit codes:

- 0 — no high-severity findings;
- 2 — one or more high-severity findings;
- 1 — review configuration or input error.

The result is structured JSON containing rule id, severity, repository-relative path, message, and optional line number.
