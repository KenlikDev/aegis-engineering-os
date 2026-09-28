# Implementation Readiness Architecture

## Purpose

Implementation readiness is the fail-closed evidence boundary between workflow planning and managed execution.

It closes the gap where a work item can be in ready lifecycle state even though the engineering evidence needed by the selected workflow has not been explicitly verified.

## Inputs

Required:

- canonical work-item Markdown;
- explicit work-item kind;
- explicit version/toolchain evidence reference;
- explicit architecture applicability classification.

Optional:

- authoritative work-item provider;
- work-item ID.

The readiness gate is provider-neutral. The provider is used only to verify that an authoritative work item is in ready.

## Checks

### Requirements

The canonical requirements clarification result must contain no blocker-level questions.

### Workflow composition

The explicit work-item kind must resolve to a deterministic registry-validated composition. Unsupported kinds fail closed.

### Version evidence

A local version evidence reference must point to an existing non-empty UTF-8 file inside the target project. An HTTPS reference is preserved as an explicit external evidence reference; the gate does not pretend to have independently fetched it.

### Architecture applicability

The caller must explicitly classify architecture planning as required or not required.

When required, the existing read-only architecture planner must return no blockers.

When not required, the gate records that explicit classification. It does not derive the decision from file layout or heuristics.

### Lifecycle

When an authoritative provider is supplied, the work item must be exactly ready.

## Output

The result is deterministic and includes separate observations and blockers. It is evidence for managed execution, not permission to mutate protected branches.

## Relationship to managed execution

The intended sequence is:

requirements clarification
-> workflow composition
-> version verification
-> architecture applicability / planning
-> implementation readiness
-> managed execution
-> testing
-> review
-> delivery

The readiness gate itself remains read-only.

## Failure handling

Missing or invalid evidence blocks implementation. The agent must resolve the evidence gap or obtain the required authoritative decision; it must not weaken the gate.