# Version Verification Architecture

## Purpose

Version verification establishes a reproducible, source-pinned inventory of the versions Aegis is expected to respect during implementation.

The executable boundary does not discover arbitrary versions by heuristic. It validates explicit claims against authoritative project files and records source SHA-256 hashes.

## Evidence model

A version claim contains:

- component name;
- exact version string;
- scope;
- repository-relative source file;
- SHA-256 of the source file.

The claim itself must be supplied by the engineering context after project discovery. Aegis does not choose a version from several competing sources.

## Recording

Use `tools/version_verification.py record` with an explicit claims JSON file.

The recorder:

1. validates each claim;
2. verifies the source is inside the project;
3. verifies the source is readable UTF-8;
4. verifies the claimed version string is present;
5. computes the source SHA-256;
6. writes deterministic `.aegis/version-evidence.json` or the explicit output path.

Recording never installs, upgrades, downgrades, or invokes project build tools.

## Validation

Use `tools/version_verification.py validate` against the recorded evidence.

Validation recomputes every source hash and checks every claimed version string again. Source drift invalidates the evidence.

The result is suitable as an input to implementation readiness.

## External verification

The evidence format records whether external compatibility verification is pending. A pending external check is not silently reported as complete.

Offline operation may preserve a valid local source inventory while marking external documentation verification as pending.

## Canonical provenance adapter

A validated version inventory can be emitted as the provider-neutral evidence envelope without changing the specialized version-evidence JSON:

    python3 tools/version_verification.py validate \
      /path/to/project \
      /path/to/project/.aegis/version-evidence.json \
      --revision <exact-project-revision> \
      --evidence-output /tmp/version-verification-evidence.json

The adapter preserves every claim and `source_sha256`. When `external_verification_pending` is true, the canonical artifact uses status `pending` and records the unresolved compatibility limitation as uncertainty. A supplied project revision is preserved as canonical observation provenance.

## Relationship to implementation readiness

Implementation readiness must consume a structurally validated version-evidence artifact rather than accepting arbitrary non-empty text.

Version verification remains evidence production/validation; architecture and product decisions remain separate boundaries.

## Safety

The version-verification boundary never:

- silently selects a version;
- executes arbitrary project commands;
- changes dependency declarations;
- installs tools;
- mutates protected branches;
- claims external compatibility without evidence.