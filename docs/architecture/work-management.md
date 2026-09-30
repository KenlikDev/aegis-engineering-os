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


## Delivery lifecycle

The delivery boundary is implemented in \`tools/delivery.py\`. It remains provider-neutral at the orchestration contract level and keeps GitHub REST details inside \`GitHubPullRequestProvider\`.

A work item may create a pull request only from \`review\`. The source branch must satisfy the Aegis \`ai/<kind>/...\` task-branch policy, and the target must be an explicit \`ai/*\` integration branch. Protected \`develop\` and \`main\` are never valid delivery targets for this bridge.

GitHub's generic \`closed\` issue state is not an Aegis lifecycle state. The provider must see an explicit \`aegis:status:<state>\` label before returning an Aegis lifecycle state; a closed issue without that label is ambiguous and fails closed. In particular, \`state_reason=completed\` does not substitute for the Aegis \`done\` transition.

PR creation is idempotent for an existing open head/base pair. A created or reused pull request is read back and its head/base are verified before the URL is attached to the work item. The pull-request creation mutation and work-item traceability mutation must both report read-after-write verification; otherwise delivery fails closed and cannot return `status=verified`.

Delivery never merges a pull request. The merge synchronization operation only reads the actual PR state and advances \`review -> integration\` when the PR is closed with a verified merge into the configured integration branch and the source branch matches the expected task branch. The review -> integration transition must itself report read-after-write verification before synchronization can return `status=verified`.

A PR that is still open or unmerged does not mutate the work item. A mismatched source or target branch is a hard failure.


## Lifecycle mutation provenance

The lifecycle provider returns `MutationEvidence` as the provider-neutral result of a transition, comment, or traceability operation. Canonical provenance is derived only after the provider-specific operation completes and any read-after-write verification has run.

A mutation with `verified=True` becomes canonical `verified`. A mutation with `verified=False` remains canonical `unknown` with explicit uncertainty. The adapter does not retry, repair, or reinterpret the provider result.

Higher-level execution boundaries must enforce this invariant at their own return boundary. They must not synthesize `verified=True` from a successful transport or command result. Quality-gate synchronization and managed execution therefore fail closed when traceability, comment, or lifecycle mutation evidence is unverified.

## Release promotion readiness

Promotion from \`ai/integration\` into \`develop\` or \`main\` is a separate human-controlled delivery stage.

\`tools/promotion_readiness.py\` provides a read-only evidence gate. It verifies exact current branch SHAs, source/target divergence, protected status, and a successful \`Aegis Validation\` workflow run on the exact \`ai/integration\` SHA.

A readiness result is evidence, not a merge authorization. Protected-branch policy and human approval remain authoritative.

## Requirements clarification

`tools/requirements_clarification.py` is the executable read-only boundary between intake and planning. It checks the canonical work-item format for a concrete title, intent, in-scope/out-of-scope boundaries, observable acceptance criteria, and verification plan. Missing dependencies or risks are reported as warnings because some tasks legitimately have none.

A blocker result means the work item must not silently advance to `ready`. The tool emits deterministic questions rather than selecting the missing business or technical decision. This preserves user ownership of scope, acceptance, priorities, and commitments.


## GitHub credential destination

GitHub Issues lifecycle persistence sends bearer credentials only to the exact `https://api.github.com` API origin. Arbitrary HTTPS hosts are not accepted as API destinations.
