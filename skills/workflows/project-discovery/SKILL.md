---
name: project-discovery
description: Inspect an existing repository and establish a trustworthy technical baseline before implementation work begins.
---

# Project Discovery

## Required inspection

Determine:
- repository status and branch;
- directory structure;
- languages and build systems;
- exact toolchain and dependency versions;
- source-of-truth manifests and lockfiles;
- tests and test commands;
- CI workflows;
- deployment and container configuration;
- project instructions;
- architecture documentation;
- relevant Git history.

## Output

Produce a project baseline containing:
- architecture summary;
- technology/version inventory;
- build and test commands;
- important conventions;
- risks and constraints;
- missing knowledge;
- unresolved decisions.

Do not begin substantial implementation until the baseline is sufficient for the task.
