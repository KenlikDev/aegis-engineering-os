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
- work-item ID;
- optional explicit canonical evidence bundle;
- optional explicit evidence-set requirements contract.

The readiness gate is provider-neutral. The provider is used only to verify that an authoritative work item is in ready.

## Checks

### Requirements

The canonical requirements clarification result must contain no blocker-level questions.

### Workflow composition

The explicit work-item kind must resolve to a deterministic registry-validated composition. Unsupported kinds fail closed.

### Version evidence

A local version evidence reference must point to an existing non-empty UTF-8 file inside the target project. An HTTPS reference is preserved as an explicit external evidence reference, but the gate remains blocked because the current boundary does not independently verify remote contents.

### Architecture applicability

The caller must explicitly classify architecture planning as required or not required.

When required, the existing read-only architecture planner must return no blockers.

When not required, the gate records that explicit classification. It does not derive the decision from file layout or heuristics.

### Explicit evidence-set requirements

When both `--evidence-bundle` and `--evidence-set-requirements` are supplied, implementation readiness validates the canonical bundle and then evaluates the bundle against the supplied machine-readable requirements. The requirements consumer uses deterministic one-member-per-selector matching and can optionally require an exact evidence `revision`.

A satisfied evidence set contributes a `passed` readiness observation and preserves the bundle ID and requirement counts. A malformed or unsatisfied evidence-set contract contributes a `blocked` observation and a readiness blocker. It does not change the other readiness checks and does not become authorization by itself.

The readiness gate never derives requirements from the work-item document, bundle purpose, free-form evidence text, or workflow composition. Omitting the evidence-set inputs preserves the existing readiness contract; supplying only one of them is rejected.

### Canonical provenance adapter

The readiness result can be emitted as canonical evidence without changing the specialized readiness JSON:

    python3 tools/implementation_readiness.py \
      /path/to/project/work-item.md \
      --project-root /path/to/project \
      --kind feature \
      --version-evidence-ref .aegis/version-evidence.json \
      --architecture-not-required \
      --evidence-bundle .aegis/readiness-bundle.json \
      --evidence-set-requirements .aegis/readiness-requirements.json \
      --evidence-output /tmp/implementation-readiness-evidence.json

The adapter preserves all readiness observations, blockers, composition steps, lifecycle state, architecture applicability, version-evidence metadata, and explicit evidence-set provenance. A blocked result is `failed`. A ready result with external version verification still pending is `pending`; it is never silently promoted to `verified`.

## Lifecycle

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