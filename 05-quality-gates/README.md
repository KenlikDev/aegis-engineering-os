# Quality Gates

Quality gates are evidence required before integration.

## Baseline gates

1. Formatting and code style.
2. Static analysis and lint.
3. Relevant unit tests.
4. Relevant integration and end-to-end tests.
5. Build and package verification.
6. Security checks appropriate to the stack.
7. Version compatibility verification.
8. Documentation consistency.
9. Git diff and secret review.
10. CI validation.

A project may add stricter gates. A gate must not be weakened only because it is inconvenient.

## Failure handling

A failed gate triggers diagnosis and remediation. Suppression, deletion, disabling, or falsifying of the check is not an acceptable fix.
