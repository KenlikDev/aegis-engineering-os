---
name: aegis-orchestrator
description: Coordinate autonomous software development by selecting roles and skills, managing decision authority, enforcing quality gates, and controlling Git and GitHub workflow.
---

# Aegis Orchestrator

## Mission

The orchestrator is the top-level operating procedure for an Aegis session. It determines what must happen before implementation and prevents blind coding.

## Session protocol

### 0. Establish language and authority

- Interact with the user in Russian.
- Identify whether the user supplied an idea, requirements, or full delegation.
- Determine which decisions remain with the user and which are delegated.

### 1. Repository discovery

Inspect:
- repository status and branch;
- directory structure;
- build system;
- source-of-truth manifests and lockfiles;
- runtime and toolchain versions;
- tests;
- CI;
- deployment files;
- project instructions;
- architecture documentation;
- relevant Git history.

Do not make product changes during discovery.

### 2. Requirement analysis

Convert the request into:
- goal;
- users;
- required behavior;
- non-functional constraints;
- acceptance criteria;
- out-of-scope items;
- unresolved decisions.

If the user has no idea and delegates discovery, invoke product-discovery instead of inventing a random feature.

### 3. Skill selection

Load only the skills required by the task:
- role skills;
- technology skills;
- workflow skills;
- quality and security skills;
- project-local skills.

If a required skill is missing, invoke knowledge-gap handling.

### 4. Plan

Create a concise plan with dependency order, affected components, tests, documentation, risks, and rollback considerations.

For material architecture decisions, create or update an ADR.

### 5. Implement

Work only on an ai/* task branch. Never directly modify main or develop.

### 6. Verify

Run applicable quality gates:
- formatting;
- lint and static analysis;
- unit tests;
- integration and end-to-end tests;
- build;
- security checks;
- version compatibility checks;
- documentation checks.

If a gate fails, diagnose and fix the root cause. Do not weaken the gate.

### 7. Review

Perform an independent review pass that assumes the implementation may contain defects. Check correctness, edge cases, concurrency, error handling, security, performance risks, duplicated logic, unnecessary complexity, testing, documentation, and scope.

### 8. Git hygiene

Before commit:
- inspect status;
- inspect the complete diff;
- remove unrelated changes;
- confirm no secrets are staged;
- create coherent commits.

If a mistake is found before push, clean local history using amend, fixup, or rebase when appropriate.

### 9. Remote workflow

Push only clean, verified checkpoints.

Target flow:
ai/* -> ai/integration -> develop -> main

The agent may prepare and update PRs, but human approval controls protected branches according to repository policy.

### 10. Report

Return a Russian report covering completed work, important decisions, verification evidence, unresolved items, and required user input.

## Stop conditions

Ask the user when:
- a critical product decision is ambiguous;
- an irreversible destructive action is required;
- production credentials or access are required and unavailable;
- a security boundary is unclear;
- the user must choose between materially different business outcomes;
- external facts are necessary but cannot be verified.
