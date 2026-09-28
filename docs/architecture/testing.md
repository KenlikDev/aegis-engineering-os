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

The result preserves:

- gate order;
- required/optional classification;
- pass/fail/timeout state;
- exit codes;
- bounded redacted output;
- required failure IDs;
- the validated testing contract.

The workflow itself adds no hidden pass/fail rules beyond the existing quality-gate contract.

## Safety

Testing is execution, so it may run project-declared commands. It does not mutate project source or Git state itself. Any lifecycle mutation is explicit provider synchronization delegated to the existing quality-gate contract.

Protected branches remain outside the workflow boundary.
