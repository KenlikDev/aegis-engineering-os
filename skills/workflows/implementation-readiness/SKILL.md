---
name: implementation-readiness
description: Establish a fail-closed evidence gate between workflow planning and managed implementation without inventing missing decisions.
---

# Implementation Readiness

## Objective

Determine whether a work item has enough explicit, verified engineering evidence to enter managed implementation.

The gate is read-only. It does not execute project commands or mutate the project.

## Required inputs

- canonical work-item Markdown;
- explicit work-item kind;
- explicit toolchain/version evidence reference;
- explicit architecture applicability classification;
- optional authoritative lifecycle provider and work-item ID.

## Checks

The gate verifies:

1. requirements clarification has no blocker-level questions;
2. the explicit work-item kind maps to a registry-validated workflow composition;
3. the version-evidence reference points to a non-empty project-local UTF-8 file; external URLs are recorded but do not pass readiness without independent verification;
4. architecture planning passes when architecture impact is explicitly classified as required;
5. lifecycle state is exactly ready when a provider is supplied.

Architecture not required must be an explicit classification. The gate never infers that decision from repository structure.

## Result

The output contains:

- work-item identity and explicit kind;
- lifecycle observation;
- requirements status;
- workflow composition;
- version evidence reference;
- architecture applicability and result;
- deterministic observations;
- blockers.

A ready result means all required evidence checks passed. A blocked result means the evidence is insufficient.

## Safety

The gate never:

- invents product scope or technical decisions;
- infers work-item kind;
- infers architecture applicability;
- executes tests or arbitrary commands;
- changes source files;
- changes lifecycle state;
- creates branches or pull requests;
- modifies protected branches.

Managed execution must not bypass this gate when the required readiness inputs are part of the execution contract.