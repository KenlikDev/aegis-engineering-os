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

## Requirements clarification

Before advancing an intake item into planning or ready state, run the read-only requirements clarification workflow when the canonical work-item document is available. Blocker-level questions must be answered by the user or an authoritative project source; Aegis must not invent the missing decision.

## Architecture planning

After a work item reaches ready, run the read-only architecture planning workflow before implementation when the task has architecture-relevant constraints or affected components. The planner must verify ready state when a lifecycle provider is supplied. It never changes lifecycle state and must not invent architecture decisions.

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

## Testing

During the verification stage, run the read-only testing workflow against the project-declared quality-gate manifest. It must not infer test commands. Required gate failures remain blockers and optional gates remain visible without being promoted to required status.

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

## Runtime composition

When used with managed OpenHands execution:

1. require the authoritative work item to be `ready`;
2. record the generated task branch;
3. transition `ready -> in_progress`;
4. execute through the verified runtime boundary;
5. on successful execution and Git verification, record conversation/evidence traceability;
6. transition `in_progress -> verification`;
7. on execution or post-execution boundary failure, transition `in_progress -> blocked` and record safe failure metadata.

The runtime never advances automatically to `review`, `integration`, or `done`. Those states require the applicable quality gates and delivery workflow.

## Quality verification

The quality-gate runner consumes the target project's explicit `.aegis/quality-gates.json` contract. It executes the declared gates in order without a shell and records bounded redacted evidence.

When a provider is configured and the work item is in `verification`:

1. execute every declared gate;
2. keep optional failures visible without treating them as required blockers;
3. transition to `review` only when all required gates pass;
4. transition to `blocked` when any required gate fails or times out.

The runner does not infer project commands or automatically bypass missing tools, malformed manifests, or failed required gates.
