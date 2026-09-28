---
name: testing
description: Validate and execute an explicit project testing and quality-gate contract without inventing test commands or bypassing required failures.
---

# Testing

## Objective

Execute the project's declared testing and quality contract after implementation and before review.

## Entry conditions

- the target project is readable;
- a project-local `.aegis/quality-gates.json` manifest exists;
- the manifest is valid and declares at least one required gate;
- when lifecycle synchronization is requested, the authoritative work item is exactly in `verification`.

Testing never infers commands from language, repository layout, or tool availability.

## Contract

The testing workflow delegates command execution to `tools/quality_gates.py`, which remains the canonical executor.

The workflow:

1. validates the explicit manifest;
2. verifies the optional lifecycle precondition;
3. executes every declared gate in manifest order;
4. preserves required and optional gate semantics;
5. returns bounded redacted output;
6. when explicitly configured with a provider, uses the existing quality-gate lifecycle synchronization contract.

A required gate failure is never bypassed.

## Execution

Validate only:

    python3 tools/testing.py /path/to/project --dry-run

Run the explicit contract:

    python3 tools/testing.py /path/to/project

Run with lifecycle synchronization:

    GITHUB_TOKEN="$TOKEN" python3 tools/testing.py /path/to/project \
      --work-item-repository OWNER/REPO \
      --work-item-id 123 \
      --evidence-path /tmp/aegis-testing.json

## Safety

The workflow never:

- invents test commands;
- treats optional gates as required;
- bypasses failed required gates;
- changes source code;
- changes Git refs;
- merges pull requests;
- modifies protected branches.

The testing workflow is an execution boundary, not a second test runner.
