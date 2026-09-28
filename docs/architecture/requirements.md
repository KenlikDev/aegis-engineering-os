# Requirements Clarification Architecture

## Purpose

Requirements clarification is the boundary between user intent and autonomous engineering planning.

Aegis may identify missing information, but product intent remains owned by the user.

## Required contract

A work item is ready for implementation planning only when it contains:

- a concrete title;
- an explicit outcome;
- explicit in-scope work;
- explicit out-of-scope work;
- observable acceptance criteria;
- a verification plan.

Missing dependencies or risks are warnings, because some tasks genuinely have none. The workflow records that absence rather than inventing a dependency.

## Evidence model

The executable tool reads the canonical Markdown work-item format and returns deterministic question ids such as:

- identity.title;
- intent.outcome;
- scope.in;
- scope.out;
- acceptance.criteria;
- verification.plan.

Every blocker includes section-level evidence explaining what is missing.

## Canonical provenance

The clarification report can be adapted into the canonical evidence envelope with `--canonical-evidence-output`. The adapter preserves deterministic question IDs, severity, sections, question text, evidence text, and summary counts.

A ready report maps to canonical `verified`; unresolved blocker questions map to `failed`. Warnings do not become blockers during adaptation.

This output is additive and does not answer the questions or change the work item.

## User agency

The clarification workflow does not select a priority, make a business commitment, invent an acceptance criterion, or decide disputed scope.

It turns ambiguity into an explicit question that can be answered by the user or an authoritative project source.

## Lifecycle

intake
-> requirements clarification
-> planned
-> ready
-> implementation

A work item with unresolved blocker questions must not silently advance to ready.
