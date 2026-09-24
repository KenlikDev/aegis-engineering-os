---
name: work-item-lifecycle
description: Create, plan, execute, track, and close engineering work items while linking them to branches, pull requests, verification evidence, and delegated roles.
---

# Work Item Lifecycle

## Trigger

Use for every non-trivial engineering task, feature, bug, refactor, infrastructure change, or Aegis maintenance task.

## Intake

1. Detect the project's available work-management providers.
2. Select exactly one authoritative provider.
3. Reuse an existing work item when it already represents the requested outcome.
4. Otherwise create a work item before substantial implementation.
5. Record the work item ID in the task context.

## Planning

Record:

- goal and expected outcome;
- scope and non-goals;
- acceptance criteria;
- dependencies;
- risks;
- responsible roles;
- verification plan.

Create subtasks only when they clarify ownership or dependencies.

## Execution

1. Create an ai/* branch associated with the work item.
2. Keep the work item status synchronized with meaningful progress.
3. Link the branch and pull request to the work item.
4. Add material decisions and blockers to the work item.
5. Keep routine implementation details in Git rather than using issue comments as a code log.

## Verification

Before completion:

- acceptance criteria are checked;
- required quality gates pass;
- required security checks pass;
- independent review is complete;
- linked branch and PR are identified;
- unresolved risks are recorded.

A failed gate moves the item to a blocked or active state and triggers root-cause remediation.

## Scope change

When implementation reveals materially new scope:

1. update the work item;
2. distinguish required scope from optional follow-up work;
3. create a separate work item for independent follow-up work;
4. obtain user approval when the change crosses the decision-escalation boundary.

Do not silently expand the task.

## Completion

Transition to the terminal state only after the definition of done is satisfied.

Close the work item through its provider when supported. Preserve traceability to the merged or staged pull request.

## Provider rule

Never assume a specific work-management provider is available. Use the provider skill selected by capability discovery.
