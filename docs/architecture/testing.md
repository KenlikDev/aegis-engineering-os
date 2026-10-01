# Testing Workflow Architecture

## Purpose

The testing workflow is the controlled boundary between implementation verification and review. It does not create a second test runner. The existing `tools/quality_gates.py` remains the canonical executor for project-declared commands.

## Contract

A project must explicitly declare its quality and testing commands in `.aegis/quality-gates.json`.

The testing workflow validates:

- the project root;
- the manifest location;
- manifest schema and gate definitions;
- at least one required gate;
- optional lifecycle state.

It then delegates execution to the quality-gate implementation.

No command is inferred from programming language, file names, package managers, or installed tools.

## Lifecycle

With no provider, the workflow is a local verification boundary and returns structured evidence.

With a work-item provider:

`verification -> review` occurs only through the existing quality-gate synchronization contract after every required gate passes.

A required failure transitions the work item to `blocked` through that same existing contract.

The testing boundary never advances work directly to `integration` or `done`.

## Evidence

## Canonical provenance adapter

The testing workflow can emit the existing result into the canonical evidence envelope with `--canonical-evidence-output`. An optional `--revision` records the exact project revision associated with the observed run.

The adapter uses the already redacted testing result. It does not rerun commands, inspect credentials, infer additional pass/fail rules, or change lifecycle semantics.

The result preserves:

- gate order;
- required/optional classification;
- pass/fail/timeout state;
- exit codes;
- bounded redacted output;
- required failure IDs;
- the validated testing contract.

The workflow itself adds no hidden pass/fail rules beyond the existing quality-gate contract.

## Pull request revision identity

For non-closed pull-request events, validation checks out the exact pull-request head SHA rather than GitHub's synthetic merge ref. A dedicated checkout assertion verifies that the executed workspace is exactly that revision. The merged `ai/integration` close-event path continues to check out the actual merge commit SHA.

This keeps the workflow run's revision identity aligned with the source files whose validation actually executed.

## Validation run concurrency

The repository validation workflow is required to produce a completed post-merge validation for the actual `ai/integration` merge commit.

Push-triggered validation runs include the exact commit SHA in their concurrency group and are never cancelled by later push events. Normal non-closed pull-request validation runs remain cancellable so obsolete synchronize runs do not accumulate. Closed pull-request events are also non-cancellable, preserving the post-merge validation checkpoint for merged pull requests targeting `ai/integration`.

## Safety

Testing is execution, so it may run project-declared commands. It does not mutate project source or Git state itself. Any lifecycle mutation is explicit provider synchronization delegated to the existing quality-gate contract.

Protected branches remain outside the workflow boundary.
\n## Lifecycle synchronization invariant\n\nWhen the testing boundary synchronizes a work item, each material traceability, comment, and lifecycle mutation must return `MutationEvidence.verified=true`. Local gate success and provider transport success are separate facts; an unverified provider mutation must fail the synchronization boundary closed.\n