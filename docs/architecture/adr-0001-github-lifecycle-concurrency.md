# ADR-0001: Serialize GitHub lifecycle transitions with Git refs

## Status

Accepted

## Context

`GitHubIssuesProvider.transition` historically implemented `expected_state` as a read-before-write check. GitHub's Update Issue endpoint does not document an `If-Match` conditional PATCH contract, so a stale writer could pass the initial GET and overwrite a newer lifecycle state before the read-after-write verification.

## Decision

Use one Git ref per work item at `refs/aegis/locks/work-item/<id>` as a provider-level serialization primitive.

An uncontended lock is created with the Git references create endpoint. When a lock ref already exists, a free lock or an expired lease is advanced by creating a child commit and updating the ref with `force=false`. GitHub documents that non-forced reference updates do not overwrite work and return `409 Conflict` on conflict. Because every candidate update is a direct descendant of the observed lock commit, two writers racing from the same observed ref cannot both advance it.

Lock metadata is stored in the lock commit message and includes the work-item number, owner UUID, mode, and expiry. Leases are bounded to avoid permanent locks after process failure. Release is another fast-forward-only update to a free-lock commit; the implementation never performs an unconditional delete that could remove another writer's newly acquired lock.

Lifecycle state is re-read after lock acquisition, before the issue PATCH, so `expected_state` is enforced inside the serialization boundary rather than only before it.

## Consequences

- Lifecycle transitions by cooperating provider instances are serialized per work item.
- A stale provider update fails closed on either issue-state drift or Git-ref conflict.
- Lifecycle transitions require GitHub Contents write permission in addition to issue mutation permission.
- The validation workflow keeps `contents: read`; it does not use the lifecycle lock write path.
- Direct manual issue edits do not participate in the provider lock and therefore are not covered by the provider-level serialization guarantee.
- Lock refs accumulate small Git commits over the life of each work item and require bounded stale-lock handling.

## Alternatives considered

GitHub REST conditional PATCH with `If-Match` was rejected because the Update Issue endpoint does not document conditional unsafe-method support. GitHub GraphQL `updateRefs` is a stronger atomic primitive, but it is not exposed by the repository's current GitHub connector, so introducing an unsupported connector dependency would broaden the change without an executable integration path.

## Verification

Deterministic provider tests cover a competing writer winning the lock ref update and a work-item state change between the initial precondition read and the locked re-read. The acceptance path also requires the repository's normal validation workflow before integration.
