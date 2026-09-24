# Context Loading Strategy

Aegis uses progressive disclosure to avoid loading the entire knowledge base into every session.

## Mandatory context

Load:
- constitution;
- orchestrator;
- user communication policy;
- active project instructions.

## Dynamic context

Load only the roles, technology skills, workflows, and quality/security guidance relevant to the current task.

## Deep references

Load detailed references only when the active skill requires them.

## Session pinning

The active Aegis version and selected skills are fixed for a session. Updating the local knowledge base does not silently change the current session.

## Principle

More context is not automatically better. Context must be relevant, current, internally consistent, and sufficient for the decision being made.
