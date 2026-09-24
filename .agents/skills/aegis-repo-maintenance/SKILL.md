---
name: aegis-repo-maintenance
description: Maintain the Aegis repository while preserving its constitution, validation model, versioning, and skill quality.
---

# Aegis Repository Maintenance

When changing Aegis itself:

1. Read AGENTS.md and the constitution.
2. Identify the intended version impact.
3. Keep canonical engineering content in English.
4. Update validators and tests when introducing new invariants.
5. Treat new skills as candidates until validated.
6. Keep changes coherent and reviewable.
7. Run the repository validator before commit.
8. Inspect the complete diff before push.
9. Do not rewrite pushed shared history.

Aegis is itself a product and must follow the same engineering discipline that it asks target projects to follow.
