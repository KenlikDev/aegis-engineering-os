---
name: jira
description: Use Jira as an optional authoritative work-management provider when the project has an active Jira workflow and integration access.
---

# Jira

## Applicability

Use only when Jira is configured for the project and is the selected authoritative work-management provider.

## Discovery

Determine:

- Jira site and project;
- available issue types;
- required fields;
- workflow states and transitions;
- project permissions;
- existing issue conventions.

Never assume field IDs, issue types, transition IDs, or workflows are universal.

## Work creation

Create an issue with:

- outcome;
- scope and non-goals;
- acceptance criteria;
- dependencies;
- relevant risks;
- assigned role or owner when appropriate.

Create subtasks only when the project workflow supports them and the dependency structure justifies them.

## Execution

- preserve the Jira issue key in the branch and pull request;
- update status at meaningful lifecycle boundaries;
- record material decisions and blockers;
- link GitHub pull requests or commits when GitHub is the code host.

## Completion

Move the Jira issue to its terminal workflow state only after acceptance criteria and applicable quality gates pass.

## Safety

Do not create duplicate Jira and GitHub backlogs unless explicit synchronization is configured.

Do not assume a successful API response means the project's workflow semantics are correct; verify the resulting issue state.
