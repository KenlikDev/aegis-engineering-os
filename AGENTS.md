# Aegis Engineering OS Agent Instructions

## Mission

Aegis is an experimental engineering operating system for autonomous software development. This repository defines the rules, workflows, skills, templates, validators, and governance used by the system.

## Language policy

- Communicate with the user in Russian unless the user explicitly requests another language.
- Write code, identifiers, code comments, Git commits, pull requests, ADRs, and canonical engineering documentation in professional English.
- Russian documentation belongs only in explicitly marked user-facing documentation such as docs/ru/.
- Never add Russian comments to production code merely to translate an English implementation.

## Authority model

The user is the product owner and has final authority over product intent, business priorities, acceptable risk, spending, production changes, and explicitly delegated decisions.

The agent owns routine engineering decisions and should make them autonomously when they do not materially affect product behavior, cost, security, privacy, or irreversible operations.

Ask the user when a decision has material product, business, security, privacy, cost, compliance, or irreversible-data consequences. When the user explicitly delegates a decision area, record the scope and proceed within it.

## AI provider policy

- Keep Aegis model-agnostic.
- The user explicitly chooses the active AI provider, agent surface, and model.
- Do not rank providers or silently switch providers after quota, network, or model failures.
- Keep provider origins explicit; the default registry may contain US-origin cloud providers and LOCAL backends such as Ollama.
- Treat subscription login and API-key access as separate billing/authentication modes.
- Never commit provider API keys, OAuth tokens, or cached credentials.
- Do not assume that a consumer subscription includes API usage.

## Evidence and state verification

- User statements are authoritative for intent, preferences, and delegated decisions, but are not proof of independently observable state.
- Verify current state from the strongest available authoritative source before relying on a state-dependent claim.
- After material mutations, read the resulting state back when supported.
- Distinguish verified facts, user-provided claims, assumptions, and unresolved uncertainty.
- Never turn model memory, stale observations, or confident wording into evidence.
- When state-dependent evidence conflicts, investigate the discrepancy before making the state-dependent decision.

## Work management

- Every non-trivial task must have a stable work item before substantial implementation.
- GitHub Issues is the default work-management provider.
- Jira may be used when it is configured and is the project's established authoritative tracker.
- Confluence may be used for persistent external knowledge; it is not a task queue unless the project explicitly defines it as such.
- Select exactly one authoritative work-management provider for each task.
- Link the work item to its task branch, pull request, verification evidence, and final outcome.
- Do not create duplicate backlogs across providers unless explicit synchronization is configured.
- Create subtasks only when they clarify ownership, independent deliverables, or dependencies.

## Engineering rules

1. Inspect the existing repository before changing it.
2. Detect the actual language, framework, toolchain, dependency, and runtime versions before relying on version-sensitive behavior.
3. Prefer official documentation and repository-local source-of-truth files for version verification.
4. Never silently target a latest version.
5. Preserve existing architecture and conventions unless a deliberate change is justified.
6. Do not disable, weaken, delete, or bypass tests or quality gates to make CI pass.
7. Never commit secrets, credentials, tokens, private keys, or generated sensitive data.
8. Keep changes narrowly scoped to the task.
9. Add or update tests when behavior changes.
10. Update canonical documentation when architecture, public behavior, or operational procedures change.
11. Record significant architectural decisions as ADRs.
12. Validate before commit and inspect the final diff before push.
13. Do not claim completion without evidence.

## Git policy

- Never work directly on main or develop.
- Use task branches under ai/.
- The shared AI integration branch is ai/integration.
- Target flow: ai/* -> ai/integration -> develop -> main.
- Treat develop and main as human-controlled protected branches.
- Prefer coherent, atomic commits.
- Preserve work-item identity in branch and pull-request metadata.
- If an error is discovered before a commit is pushed, prefer amend, fixup, or local history cleanup instead of noisy corrective commits.
- Once a commit has been pushed to a shared remote branch, do not rewrite history unless an explicit repository policy allows it.
- Do not push every minor change. Push at meaningful, verified checkpoints.
- For long-running work, a clean recovery checkpoint may be pushed when it reduces the risk of losing work.
- Never force-push develop or main.

## Knowledge safety

New or modified global knowledge follows this lifecycle:

untrusted -> candidate -> validated -> known-good -> active

A failed candidate must not replace the active knowledge set.

## Offline behavior

Aegis must continue using the last active known-good local version when remote access is unavailable.

When current external information cannot be verified offline, say so explicitly and mark it for later re-verification. Never fabricate freshness.

## Completion gate

A task is complete only when the applicable quality gates pass or an explicit, documented exception exists, and its authoritative work item reflects the resulting state.
