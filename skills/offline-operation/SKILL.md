---
name: offline-operation
description: Continue engineering work with a locally pinned known-good Aegis version when network or GitHub access is unavailable.
---

# Offline Operation

## Local source of truth

The agent must have a local clone of Aegis and a pinned active version.

Record:
- Aegis version;
- commit SHA;
- active skill versions.

## Online

When online:
- fetch remote metadata;
- detect newer validated versions;
- download candidates without replacing the active version;
- validate candidates separately;
- promote only after validation.

## Offline

When offline:
- continue with the active known-good version;
- use local project source;
- use local dependency caches;
- use cached documentation where available.

For current external facts that cannot be checked:
- mark them unverified and pending;
- do not fabricate current information.

## Recovery

When connectivity returns:
1. fetch;
2. validate candidates;
3. reconcile pending external verification;
4. update local mirror;
5. keep the active session pinned to its original Aegis version until the session ends.

A failed update must never replace the last known-good active version.
