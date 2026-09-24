---
name: project-discovery
description: Inspect an existing repository and establish a trustworthy technical baseline before implementation work begins, including work-management and external knowledge configuration.
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
- relevant Git history;
- configured work-management provider;
- available external knowledge integrations.

## Output

Produce a project baseline containing:
- architecture summary;
- technology/version inventory;
- build and test commands;
- important conventions;
- work-management system and source-of-truth rules;
- external knowledge integrations;
- risks and constraints;
- missing knowledge;
- unresolved decisions.

Do not begin substantial implementation until the baseline is sufficient for the task and the work-management source of truth is known.
