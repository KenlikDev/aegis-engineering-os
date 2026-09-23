---
name: version-verification
description: Determine the exact toolchain, framework, dependency, and runtime versions used by a project and verify version-sensitive implementation against authoritative sources.
---

# Version Verification

## Objective

Prevent the agent from implementing against a newer or imaginary API than the project actually uses.

## Required sequence

1. Inspect package, build, toolchain, and lock files.
2. Determine effective versions used by the build.
3. Check language, compiler, runtime, and framework versions.
4. Check dependencies relevant to the task.
5. Check CI and container versions when relevant.
6. Compare the intended implementation with authoritative documentation for the exact versions.
7. Record the baseline when the project does not already expose one.

## Source-of-truth priority

Prefer:
1. resolved lockfiles or dependency reports;
2. build-system manifests and version catalogs;
3. project configuration;
4. toolchain files;
5. CI configuration;
6. official vendor documentation for the exact version;
7. official release notes;
8. local cached documentation;
9. memory only as a last resort.

## Rules

- Never silently substitute latest.
- Never assume an API exists because it exists in a newer version.
- If the current version is incompatible, report the incompatibility and propose compatible options.
- Treat version upgrades as intentional changes with their own tests and risk assessment.
- Do not mix unrelated dependency upgrades into feature work.

## Offline mode

When external verification is unavailable, use repository source-of-truth files and local cached documentation. Mark external verification as pending. Do not claim current external compatibility without evidence.

## Required result

The project must be able to answer:
- exact versions in use;
- source of each important version;
- compatibility status;
- pending external verification.
