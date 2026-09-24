---
name: aegis-update-validation
description: Validate a new Aegis version or skill candidate before promoting it over the active known-good version.
---

# Aegis Update Validation

## Process

1. Identify the candidate version and commit.
2. Validate repository structure and skill metadata.
3. Check for contradictions with the constitution.
4. Run skill scenario tests.
5. Compare behavior with the previous known-good version.
6. Run representative project tasks when available.
7. Record failures and unresolved risks.
8. Promote only when acceptance criteria pass.
9. Preserve the previous known-good version for rollback.

A new Aegis version must never become active solely because it is newer.
