---
name: user-communication
description: Communicate with the product owner in Russian while keeping engineering artifacts professional and canonical in English.
---

# User Communication

## Language

Use Russian for direct interaction with the user.

Use English for:
- source code;
- identifiers;
- code comments;
- Git commits;
- branches;
- issues;
- pull requests;
- ADRs;
- canonical engineering documentation.

Russian documentation may exist as a separate explanatory layer for the user.

## Technical explanations

Explain decisions using:
- goal;
- impact;
- trade-offs;
- risk;
- recommendation.

Do not force the user to choose implementation details that have little product impact.

## Questions

Ask only when:
- the answer materially affects product behavior;
- the user must choose a business or UX preference;
- a security or privacy decision is required;
- a cost decision is required;
- an irreversible action is involved;
- requirements are contradictory or incomplete.

For multi-decision work, create a concise questionnaire with checkboxes or explicit options. Each question should state why it matters.

Separate:
- decisions the user must make;
- decisions the AI can make;
- optional preferences;
- assumptions.

## Reporting

After work, summarize in Russian:
- what changed;
- why important decisions were made;
- verification performed;
- known risks;
- exact user decisions needed.


## User technical profile

Treat the product owner as technically literate and capable of programming, while not assuming professional commercial software-development experience.

Default communication should be:
- clear rather than simplistic;
- technically accurate;
- Russian-first;
- explicit about unfamiliar professional practices and trade-offs;
- capable of becoming detailed on request.

Do not hide important engineering context merely because the user may not know a term. Explain the term briefly and continue.
