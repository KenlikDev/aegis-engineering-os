---
name: confluence
description: Use Confluence as an optional persistent knowledge backend for project context, decisions, research, architecture, and operational documentation.
---

# Confluence

## Applicability

Use only when Confluence access is available and the project benefits from an external knowledge space.

Confluence is not the authoritative work queue unless the project explicitly defines it as such. Work items belong to the selected work-management provider.

## Good uses

Use Confluence for:

- project briefs and product context;
- research synthesis;
- architecture overviews;
- decision records or decision indexes;
- operational runbooks;
- onboarding material;
- cross-project knowledge that should not live only in one repository.

## Repository relationship

The Git repository remains canonical for:

- source code;
- tests;
- versioned configuration;
- repository-local instructions;
- canonical ADR files.

A Confluence page may mirror or extend this knowledge, but it must link back to the repository source when applicable.

## Updates

When publishing or updating a page:

1. identify the correct space and parent page;
2. preserve established naming and ownership conventions;
3. avoid overwriting unrelated content;
4. record the repository or work-item reference;
5. verify the resulting page and permissions when the integration supports it.

## Safety

Do not create duplicate pages for an existing canonical document unless a deliberate knowledge mirror is intended.
