# Work Management

Aegis treats non-trivial engineering work as a managed work item rather than an untracked conversation.

## Work item principle

Every non-trivial task receives a stable work item before implementation begins.

A work item is the coordination record for:

- intent and scope;
- acceptance criteria;
- ownership and delegated roles;
- dependencies;
- risks;
- implementation branch;
- pull request;
- verification evidence;
- completion state.

The work item does not replace the repository. Code, tests, configuration, and canonical technical documentation remain in Git.

## Provider strategy

Aegis uses a provider-adaptive model:

1. GitHub Issues is the default provider.
2. Jira is used when the project already uses Jira as its primary work-management system and the integration is available.
3. Confluence is a knowledge backend, not a task queue.
4. Other providers may be added through the same provider contract.
5. Aegis must not create duplicate backlogs across providers unless explicit synchronization is configured.

At task intake, Aegis determines the available providers and selects exactly one authoritative work-management provider for the task.

## Lifecycle

intake -> planned -> ready -> in_progress -> verification -> review -> integration -> done

An item may enter blocked from any active state and return to the previous active state when the blocker is removed.

## Work-item identity

The work item identifier must be preserved across:

- branch name;
- commit metadata when practical;
- pull request title or body;
- external documentation;
- status updates.

For GitHub, use the issue number, for example #42.

For Jira, use the issue key, for example PROJ-42.

## Subtasks

Create subtasks when work contains independent phases, multiple specialist roles, or a dependency structure that benefits from explicit tracking.

Do not create artificial subtasks for trivial implementation steps.

## Source of truth

The authoritative work provider owns:

- status;
- priority;
- assignment;
- acceptance criteria;
- completion state;
- dependency state.

Git owns source code and canonical technical artifacts.

External knowledge systems may mirror or extend project knowledge, but they must not silently override repository truth.

## Definition of done

A work item is complete only when:

- acceptance criteria are satisfied;
- required tests and quality gates pass;
- security checks applicable to the change pass;
- required review is complete;
- linked implementation artifacts are identifiable;
- remaining risks and exceptions are recorded;
- the work item is transitioned to its terminal state.

## Executable lifecycle bridge

The provider-neutral lifecycle is implemented by `tools/work_item_lifecycle.py`. The core transition model is deliberately independent of GitHub. The GitHub adapter persists the active lifecycle state through `aegis:status:<state>` labels and maps only `done` to GitHub's closed issue state. A generic GitHub `closed` issue without an Aegis status label is ambiguous and is rejected rather than inferred as `done`.

Blocked work preserves its previous active state in an `aegis:resume:<state>` label. A blocked item can therefore resume only at the recorded state; the adapter rejects ambiguous or stale resume metadata.

The CLI exposes three controlled operations:

    python3 tools/work_item_lifecycle.py transition OWNER/REPO 53 planned --expected-state intake
    python3 tools/work_item_lifecycle.py comment OWNER/REPO 53 "Verification evidence recorded."
    python3 tools/work_item_lifecycle.py trace OWNER/REPO 53 --branch ai/feature/53-work-item-lifecycle --pull-request-url https://github.com/OWNER/REPO/pull/53 --evidence-ref artifacts/aegis-execution.json --conversation-id 12345678-1234-5678-1234-567812345678

Use `--dry-run` on transition before a provider mutation when inspecting an unfamiliar work item. Every mutation is followed by a fresh read to verify the resulting state or comment.
