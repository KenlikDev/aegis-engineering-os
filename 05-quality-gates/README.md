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

## Executable project quality gates

Project-specific verification is declared in `.aegis/quality-gates.json`. Aegis never invents arbitrary project commands during verification; the manifest is the project-owned contract.

Each gate has a stable id, an argv command array, a project-relative working directory, a timeout, and a required flag. At least one gate must be required. Commands are executed directly without a shell, in manifest order.

The runner records exit status, timeout state, duration, and bounded redacted stdout/stderr. Common credential-like environment variables are removed from the inherited gate environment before execution; manifest-defined credential-like environment variable names are also rejected. The runner does not claim that this covers secrets stored under arbitrary innocuous variable names.

The runner can synchronize an explicit work item:

`verification -> review` when every required gate passes;

`verification -> blocked` when any required gate fails or times out.

Optional gate failures remain visible in evidence but do not block the work item. Project/network sandboxing is an execution-environment concern; the runner does not pretend that a JSON manifest itself is a network security boundary.

Start from `templates/quality-gates.example.json` and replace the example command with the project's actual required gates before activating the manifest.
