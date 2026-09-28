# Aegis Engineering OS Architecture

Aegis is a modular operating system for an autonomous software-development agent running with OpenHands and a local language model.

## Layers

### Constitution

Non-negotiable principles and authority boundaries.

### Orchestrator

Determines the work mode, selects skills, sequences workflows, and enforces quality gates.

### Roles

Define responsibilities such as product management, architecture, engineering, QA, security, and operations.

### Skills

Provide focused operational knowledge.

The canonical reusable library is stored under skills/. OpenHands-compatible project-local skills are installed under .agents/skills/.

### Knowledge

Stores validated guidance, candidates, references, decisions, and lessons.

### Runtime boundary

Separates Aegis orchestration from OpenHands execution. The local Ollama path has a read-only preflight that verifies the selected profile, runtime version, and exact installed model before execution is attempted.

### Governance

Defines user authority, Git and GitHub policy, version pinning, and offline behavior.

## Design goals

- modularity;
- progressive disclosure;
- reproducibility;
- offline continuity;
- clean Git history;
- explicit decision authority;
- self-improvement without silent global degradation;
- Russian user interaction with English engineering artifacts.

## Current maturity

Version 0.1.0-alpha.1 is experimental and is expected to change after validation on real repositories.

### Current executable delivery path

The implemented engineering delivery path is:

work item
-> workflow composition
-> implementation readiness
-> execution
-> verification
-> quality gates
-> review
-> integration delivery
-> ai/integration
-> promotion readiness
-> promotion snapshot
-> owner-controlled promotion
-> main
-> release readiness
-> owner-controlled release publication

The executable boundaries are documented in:
- docs/architecture/integration-delivery.md;
- docs/architecture/promotion.md;
- docs/architecture/release.md.


### Evidence provenance

The evidence-provenance boundary provides a canonical provider-neutral envelope for material state observations. It preserves source, subject, revision, observation time, result, uncertainty, and a canonical self-hash without mutating the observed system. Provider-specific adapters remain separate.

### Evidence bundles

The evidence-bundle boundary composes already validated canonical evidence artifacts into a deterministic, self-verifying reference set. It preserves individual evidence identities and does not infer that a bundle is complete for any higher-level decision.

Implementation readiness can now emit its own canonical provenance record, allowing the readiness gate result to participate in later evidence composition without replacing its specialized contract.

Testing can now emit a canonical provenance record from its existing redacted execution result, allowing verification evidence to participate in later evidence bundles.

Security review can now emit a canonical provenance record from its deterministic findings without changing the security gate itself.

CI diagnosis can now emit canonical provenance from its read-only run/job/step evidence without changing diagnosis rules or CI state.

OpenHands execution can now emit canonical provenance from its already-redacted terminal execution result without changing the execution boundary.

Lifecycle mutation results can now emit canonical provenance after provider-specific read-after-write verification.

Knowledge-gap records can now emit canonical provenance while preserving the candidate-only activation boundary.

### Version verification

The version-verification capability records explicit project version claims as source-pinned evidence and validates them before implementation readiness. It never selects or upgrades versions.

### Implementation readiness

The implementation-readiness boundary validates that the explicitly classified work item has sufficient requirements, toolchain, architecture, composition, and lifecycle evidence before managed execution. It is fail-closed and read-only. The managed orchestrator must pass this gate before creating its task branch or invoking OpenHands.

### Workflow composition

The workflow-composition boundary converts an explicit work-item kind into a deterministic ordered capability set and validates every referenced skill against the registry. It does not infer task kind or execute workflows.

### Refactoring

The refactoring workflow composes requirements clarification, applicable architecture planning, verified baseline testing, normal implementation, post-change testing, and independent review. It does not introduce a separate mutation or test runner.

### Testing

The current testing execution boundary is `tools/testing.py`, which validates and delegates to the canonical `tools/quality_gates.py` runner. It never infers project test commands.

### Architecture planning

The current executable planning path is:

requirements clarification
-> planned
-> ready
-> architecture planning
-> implementation

The architecture planning boundary is documented in docs/architecture/architecture-planning.md. It is read-only and does not advance lifecycle state.
