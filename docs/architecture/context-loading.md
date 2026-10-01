# Context Loading Strategy

Aegis uses progressive disclosure to avoid loading the entire knowledge base into every session.

## Mandatory context

Load:
- constitution;
- orchestrator;
- user communication policy;
- active project instructions.

## Workflow composition

Before loading task-specific workflow skills for an implementation-oriented work item, establish its explicit kind and use the workflow-composition boundary to determine the ordered capabilities and conditional steps.

## Implementation readiness

The readiness gate is evaluated after workflow composition and before managed execution. Only after it passes should the orchestrator load or execute implementation-specific mutation workflows.

## Dynamic context

Load only the roles, technology skills, workflows, and quality/security guidance relevant to the current task.

## Instruction refresh

Authoritative instructions are refreshed at explicit checkpoints rather than assumed to remain valid for the entire session:

1. session start and before the first repository mutation;
2. after every three substantial engineering phases or after context compaction/interruption;
3. when task scope, branch, provider, work-item kind, or decision authority changes;
4. immediately before pull-request creation/merge, protected promotion, and completion.

The minimum refresh set is AGENTS.md, 00-constitution/core-principles.md, 01-orchestrator/SKILL.md, active project instructions, and the skills governing the current operation. A refresh that changes a constraint invalidates the previous plan until the affected state is re-evaluated.

## Deep references

Load detailed references only when the active skill requires them.

## Session pinning

The active Aegis version and selected skills are fixed for a session. Updating the local knowledge base does not silently change the current session.

## Principle

More context is not automatically better. Context must be relevant, current, internally consistent, and sufficient for the decision being made.
