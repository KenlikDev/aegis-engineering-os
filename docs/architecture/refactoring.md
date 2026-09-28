# Refactoring Workflow Architecture

## Purpose

The refactoring workflow is a controlled composition of existing Aegis boundaries for behavior-preserving structural change.

It intentionally does not introduce a second implementation engine or a second testing engine.

## Boundary composition

The workflow composes:

requirements clarification
-> architecture planning when applicable
-> verified baseline testing
-> normal implementation execution
-> post-change testing
-> independent code review
-> controlled delivery

Each boundary retains its existing authority and safety rules.

## Refactoring invariant

The default refactoring contract is:

> improve internal structure without intentionally changing the explicitly accepted external behavior.

This invariant is derived from the work item. Aegis must not invent the behavior to preserve.

The work item should make relevant invariants explicit, such as:

- public API compatibility;
- observable output;
- persistence/serialization behavior;
- error semantics;
- ordering and concurrency behavior;
- performance constraints;
- security or privacy characteristics.

Not every invariant applies to every project. Only evidence-supported invariants are used.

## Baseline and regression evidence

A refactor requires a verified baseline before mutation when the project quality contract can establish one.

After the structural change, the same declared quality contract is executed again. The workflow does not infer tests from source language or repository layout.

A passing baseline is evidence about the starting state. It is not evidence that the refactored state is correct.

## Scope change

If implementation reveals intentional or unavoidable behavior change, the change must leave the refactoring boundary.

The agent must:

1. record the newly observed behavior change;
2. distinguish required scope from follow-up work;
3. obtain the required user or authoritative decision when the change is material;
4. reclassify the work as feature, bug fix, or another appropriate work type when necessary.

The workflow never hides behavior changes inside a refactor.

## Architecture decisions

Architecture planning remains read-only. Durable decisions and material alternatives are handled through the existing architecture/ADR boundaries.

The refactoring workflow does not create an ADR merely because a refactor exists.

## Delivery and Git safety

Refactoring uses the normal Aegis task branch and review flow.

It must not:

- modify `develop` or `main` directly;
- bypass quality gates;
- merge its own changes outside the established integration boundary;
- rewrite shared remote history.

## Failure handling

A failed baseline or post-change required gate is a verification failure, not a reason to weaken the contract.

A discovered scope change or unresolved invariant is a blocker until the authoritative decision is established.
