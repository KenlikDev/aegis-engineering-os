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