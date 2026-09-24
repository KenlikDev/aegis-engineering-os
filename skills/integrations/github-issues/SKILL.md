---
name: github-issues
description: Manage engineering work through GitHub Issues and connect issues with branches, pull requests, labels, comments, milestones, and completion state.
---

# GitHub Issues

## Applicability

Use when GitHub is the selected authoritative work-management provider.

## Create and plan

A GitHub Issue should contain:

- outcome and problem statement;
- scope and non-goals;
- acceptance criteria;
- dependencies;
- relevant risks.

Use labels, milestones, and assignees only when they have an established project meaning.

## Execution

- create the task branch with the issue identity preserved;
- reference the issue from the pull request;
- use closing keywords only when completion should close the issue;
- add comments for material decisions, blockers, and verification evidence;
- avoid turning comments into a duplicate source-control log.

## Subtasks

GitHub Issues does not require artificial subtasks. Use separate linked issues when work is independently trackable or materially parallel.

## Completion

Close the issue only when its acceptance criteria and the work-item definition of done are satisfied.

## Safety

Do not create a second GitHub Issue when an existing issue already represents the same work.

Do not close issues merely because a PR exists.

Do not weaken repository or branch protection to simplify issue-driven automation.
