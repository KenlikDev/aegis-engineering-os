# Work Management Architecture

## Purpose

The work-management layer turns a conversation into traceable engineering work.

## Components

### Task Intake

Receives user intent and determines whether existing work already represents it.

### Work-Management Provider

Provides issue/work-item operations:

- create;
- read;
- update;
- assign;
- transition;
- comment;
- link;
- close.

GitHub Issues is the default provider.

### Role Coordinator

Maps the work item to the roles and skills required for execution. A single local model may perform several roles sequentially, but each role uses distinct evaluation criteria.

### Delivery Tracker

Maintains links between:

work item -> task branch -> commits -> pull request -> verification evidence

### Knowledge Backend

Stores durable research and cross-project knowledge. Confluence is an optional provider; repository documentation remains canonical for versioned technical artifacts.

## Provider selection

At intake:

1. inspect project-local configuration;
2. inspect available integrations;
3. identify the project's established work-management system;
4. select one authoritative provider;
5. select optional knowledge providers independently.

Default:

- work management: GitHub Issues;
- knowledge: repository documentation;
- optional external knowledge: Confluence.

If Jira is explicitly configured as the project's source of truth, use Jira instead of GitHub Issues for task tracking.

## Synchronization rule

Do not maintain two independent backlogs.

When multiple systems are connected, record one authoritative provider and create links or mirrors only for traceability.

## User escalation

Aegis should create and manage ordinary engineering work items autonomously.

Escalate to the user when:

- creating external paid resources;
- changing a business commitment;
- changing a product priority materially;
- granting broader access than required;
- deleting or bulk-migrating external project data;
- choosing an external provider when the business consequence is material.
