# Security Review Architecture

## Purpose

Security review is a read-only gate before integration or promotion.

It produces deterministic findings from observable repository state. A finding is evidence of a specific rule violation, not a statement that the whole repository is secure or insecure.

## Checks

tools/security_review.py reviews:

- GitHub Actions trust-boundary triggers;
- explicit workflow permissions;
- broad or unnecessary write permissions;
- third-party action pinning;
- GitHub API version headers;
- executable subprocess security;
- destructive Git operations;
- direct hardcoded writes to protected refs;
- high-confidence credential patterns.

## Severity model

High findings block the review. Medium findings are visible but do not block the review alone.

## Safety boundary

The review reads repository files only. It never changes code or configuration, creates issues, changes branches, modifies GitHub permissions, or prints matched credential values.

## Lifecycle position

implementation
-> code review
-> security review
-> quality verification
-> integration

Security review can also be invoked before promotion when a high-impact change crosses a trust boundary.
