---
name: state-verification
description: Verify current external and repository state from authoritative evidence before making decisions or reporting facts, while distinguishing user intent from unverified claims.
---

# State Verification

## Core rule

Treat statements from the user, model memory, cached responses, previous session summaries, and stale observations as inputs or hypotheses, not proof of current external state.

User statements are authoritative for user intent and preferences. They are not authoritative for facts that can be independently observed.

## When verification is required

Verify current state before relying on claims about:

- repository contents, branches, commits, tags, pull requests, issues, or permissions;
- CI status, logs, checks, artifacts, or deployment state;
- branch protection, rulesets, merge settings, or repository configuration;
- toolchain, framework, dependency, runtime, or action versions;
- external work-management or knowledge systems;
- credentials, connectivity, service availability, or other operational state;
- whether a requested change already exists.

## Evidence hierarchy

Prefer the strongest currently available source:

1. direct state from the system being changed or inspected;
2. authoritative repository files, lockfiles, manifests, and generated reports;
3. fresh CI/build/test output;
4. official documentation matching the exact version;
5. recent trusted secondary evidence;
6. prior observations;
7. model memory.

Do not present lower-level evidence as stronger than a fresh direct observation.

## Freshness

When state can change, prefer a fresh observation made for the current decision.

Record the source, relevant identifier or commit, and observation time when state is material to the task.

Do not silently reuse a previously observed state after a mutation or when the state may have changed.

## Conflicting evidence

When observations disagree:

1. identify the sources and their timestamps or revisions;
2. prefer the authoritative current source;
3. investigate the discrepancy;
4. do not hide the conflict;
5. report unresolved uncertainty when reconciliation is impossible.

## Mutation discipline

Before changing external state:

- verify the target exists and is still the intended target;
- verify permissions and current configuration when relevant;
- verify the expected revision or identifier where the API supports it;
- after mutation, read the resulting state back.

## Reporting

Separate reports into:

- verified facts;
- user-provided intent or claims;
- model assumptions;
- unresolved uncertainty.

Never convert an assumption into a fact through confident wording.

## Offline behavior

When direct verification is unavailable:

- use the latest known-good local evidence only for decisions it can support;
- mark current external state as unverified;
- do not claim that remote state is current;
- avoid irreversible external mutations unless the decision authority explicitly permits operating on known-local state.

## Completion rule

A state-dependent task is complete only when the final relevant state has been verified or the remaining uncertainty is explicitly documented.
