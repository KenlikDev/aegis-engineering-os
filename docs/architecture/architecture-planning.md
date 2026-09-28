# Architecture Planning Architecture

## Purpose

Architecture planning is the executable boundary between a requirements-ready work item and implementation. It converts explicit requirements evidence into a structured plan without allowing the planner to silently become the product owner.

The workflow is intentionally deterministic and read-only. A future model-assisted planner may propose alternatives, but those proposals must remain separate from this evidence gate and must not be treated as verified decisions automatically.

## Inputs

Required:

- canonical work-item Markdown;
- a passing requirements clarification result.

Optional lifecycle verification:

- authoritative work-item provider;
- work-item identifier;
- provider must report exactly ready.

The planning contract is provider-neutral. The current GitHub Issues adapter reuses the existing lifecycle provider only to verify the ready-state precondition.

## Evidence model

The result contains four distinct classes of information:

1. **Explicit evidence** — text directly present in Technical notes, Dependencies, or Risks.
2. **Technical deductions** — deterministic conclusions derived only from explicit evidence.
3. **User-owned decisions** — questions raised by unresolved requirements blockers or authoritative decision gaps.
4. **Blockers** — information missing from the architecture contract that makes safe planning impossible.

The implementation must never present a deduction as an explicit repository fact.

## Architecture fields

The structured plan records:

- constraints;
- boundaries;
- affected components;
- non-goals;
- ADR needs;
- unresolved user-owned decisions;
- blockers.

Affected components are accepted only when explicitly named by the work item, for example through Component:, Module:, Service:, Affected component:, or explicit backtick references to repository paths or component identifiers.

This deliberate restriction prevents Aegis from inventing an architecture map from naming heuristics.

## ADR policy

The workflow identifies situations that may require durable architecture records, including:

- cross-component boundaries;
- explicit alternatives or trade-offs;
- material risk trade-offs.

The workflow does not create or accept an ADR. ADR creation remains a separate controlled documentation action after the decision is actually established.

## Lifecycle

The architecture layer follows:

requirements clarification
-> planned
-> ready
-> architecture planning
-> implementation

The architecture planner does not mutate lifecycle state. It verifies ready when a lifecycle provider is supplied and returns a plan that can be consumed by the implementation workflow.

## Safety boundary

The planner never:

- changes source files;
- changes work-item scope;
- chooses product priority;
- invents acceptance criteria;
- selects a user-owned architecture decision;
- creates or merges pull requests;
- changes Git refs;
- changes protected branches.

Missing evidence becomes a blocker or explicit question instead.
