---
name: aegis-orchestrator
description: Coordinate autonomous software development by selecting roles and skills, managing decision authority, enforcing quality gates, and controlling work-management, Git, and GitHub workflow.
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
- relevant Git history;
- configured work-management and knowledge integrations.

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

### 3. Work intake and task assignment

Invoke work-item-lifecycle for every non-trivial task.

- Reuse an existing work item when it already represents the request.
- Otherwise create a work item before substantial implementation.
- Select exactly one authoritative work-management provider.
- Record goal, scope, acceptance criteria, dependencies, risks, roles, and verification plan.
- Create subtasks when multiple independent deliverables or specialist roles justify them.
- Associate the work item with the current Aegis session.

### 4. Verification and skill selection

Before acting on any state-dependent claim, classify it as user intent, user claim, observed fact, assumption, or unresolved uncertainty. Use current authoritative evidence to resolve claims before mutation or reporting.

Invoke state-verification when the task depends on current external or repository state.

Load only the skills required by the task:

Load only the skills required by the task:
- role skills;
- technology skills;
- workflow skills;
- quality and security skills;
- project-local skills;
- selected work-management and external knowledge integrations.

If a required skill is missing, invoke knowledge-gap handling.

### 5. Plan

Create a concise plan with dependency order, affected components, tests, documentation, risks, and rollback considerations.

For material architecture decisions, create or update an ADR.

### 6. Implement

Work only on an ai/* task branch. Preserve the work-item identifier in the branch name when practical. Never directly modify main or develop.

### 7. Verify

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

### 8. Review

Perform an independent review pass that assumes the implementation may contain defects. Check correctness, edge cases, concurrency, error handling, security, performance risks, duplicated logic, unnecessary complexity, testing, documentation, and scope.

### 9. Git hygiene

Before commit:
- inspect status;
- inspect the complete diff;
- remove unrelated changes;
- confirm no secrets are staged;
- create coherent commits.

If a mistake is found before push, clean local history using amend, fixup, or rebase when appropriate.

### 10. Remote workflow

Push only clean, verified checkpoints.

Target flow:

ai/* -> ai/integration -> develop -> main

The agent may prepare and update task work items and pull requests. Each PR must identify its work item, verification evidence, and remaining risks. Protected-branch promotion remains governed by repository policy.

### 11. Work-item closure

Before terminal completion:

- verify every acceptance criterion;
- ensure the linked PR and relevant verification evidence are identifiable;
- record material decisions, blockers, and exceptions;
- transition the work item to its terminal state only after the definition of done is satisfied.

### 12. Report

Return a Russian report covering the work-item ID, completed work, important decisions, verification evidence, unresolved items, and required user input.

## Stop conditions

Ask the user when:
- a critical product decision is ambiguous;
- an irreversible destructive action is required;
- production credentials or access are required and unavailable;
- a security boundary is unclear;
- the user must choose between materially different business outcomes;
- external facts are necessary but cannot be verified;
- a required external integration is unavailable and the task cannot proceed safely without it.
