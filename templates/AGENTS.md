# Project Agent Instructions

This file is generated for a project using Aegis Engineering OS.

## Language

- Communicate with the project owner in Russian.
- Keep code, comments, commits, pull requests, ADRs, and canonical technical documentation in English.

## Instruction refresh checkpoints

These instructions are operational controls, not one-time onboarding text. Re-read the authoritative Aegis instructions at these checkpoints:

- at session start and before the first repository mutation;
- after every three substantial engineering phases or after context compaction/interruption;
- whenever the task, branch, provider, work-item kind, or decision authority changes;
- immediately before pull-request creation or merge;
- immediately before protected-branch promotion or task completion.

At minimum, refresh this file, the active Aegis orchestrator/constitution instructions, and the skills governing the current operation. If instructions changed, stop using the previous interpretation and re-evaluate the affected state before proceeding.

## Aegis

Record the active Aegis version, source commit, installed skills, and their checksums in .aegis/aegis-version.json.

## Work management

Every non-trivial task must have a work item before substantial implementation.

- GitHub Issues is the default provider.
- Jira may be selected when configured and already used as the project's authoritative tracker.
- Confluence may be selected as an external knowledge backend.
- Select exactly one authoritative work-management provider for each task.
- Link the work item to the task branch, pull request, verification evidence, and final outcome.
- Do not maintain duplicate independent backlogs.

## Repository workflow

Work on ai/* task branches.

Target promotion flow:

ai/* -> ai/integration -> develop -> main

Short-lived promotion branches may be created from the promotion target for develop/main delivery.

Never directly modify develop or main.

## Version verification

Before version-sensitive work, inspect the project's source-of-truth manifests and lockfiles and verify compatibility with the exact versions in use.

## Quality

Do not claim completion without running the applicable tests, lint/static analysis, build, and security checks, or recording an explicit documented exception.

## User interaction

Ask only product, business, security, privacy, cost, or irreversible-decision questions that genuinely require the owner's choice.
