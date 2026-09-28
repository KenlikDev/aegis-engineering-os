# Evidence Bundle Architecture

## Purpose

An evidence bundle composes already validated canonical evidence artifacts into one deterministic reference set.

A bundle is a container, not a new observation. It does not upgrade the status of its members and does not replace their individual provenance.

## Contract

A bundle contains:

- `schema_version`;
- `bundle_id`, a SHA-256 identity of the canonical bundle payload;
- `purpose`, the explicit reason the evidence set is being composed;
- `members`, each containing an exact canonical `evidence_id` and a project-relative artifact path.

Members are sorted by evidence ID and path before the bundle identity is calculated. The resulting identity is deterministic for the same purpose and member set.

## Validation

Bundle validation is fail-closed:

1. the bundle must be inside the selected project root;
2. each member path must be relative and must resolve inside the root;
3. every member artifact must exist;
4. every member artifact must pass the canonical evidence contract;
5. the recorded evidence ID must equal the validated member ID;
6. member IDs and paths must be unique and canonically ordered;
7. the bundle SHA-256 must match the canonical payload.

Changing, removing, moving, or replacing a member therefore invalidates the bundle.

## Recording and CLI

Create a bundle from canonical evidence artifacts:

    python3 tools/evidence_bundle.py create       /path/to/project       .aegis/evidence-bundle.json       "Inputs for implementation readiness"       .aegis/state-evidence.json       .aegis/promotion-evidence.json

Validate the bundle and all its members:

    python3 tools/evidence_bundle.py validate       /path/to/project       .aegis/evidence-bundle.json

The bundle tool never contacts external providers and never changes the systems represented by the evidence.

## Relationship to provenance

Canonical evidence records remain the source of truth for individual observations.

Bundles provide deterministic composition so higher-level workflows can depend on an explicit set of evidence artifacts without inventing undocumented dependencies.

A bundle does not infer completeness. A higher-level gate remains responsible for defining which evidence kinds are required for its decision.

## Security

Member paths are project-relative and symlink-resolved. Bundle metadata does not accept arbitrary URLs or credentials. Member evidence is revalidated on every bundle validation, so the bundle cannot silently preserve a stale or tampered member.

## Current integration

The bundle boundary is currently provider-neutral and filesystem-backed. Promotion and release readiness can already emit canonical evidence artifacts, while other specialized evidence schemas remain independent until explicit adapters are introduced.
