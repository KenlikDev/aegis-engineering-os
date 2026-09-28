# Aegis Engineering OS

A modular engineering operating system for autonomous software development with a local LLM and OpenHands.

> Status: Experimental alpha  
> Version: 0.1.0-alpha.1

Aegis defines the engineering rules, roles, workflows, skills, quality gates, decision authority, project memory, Git/GitHub policy, version verification, and offline behavior used by an autonomous development agent.

## Core principles

- The user communicates with Aegis in Russian.
- Code, code comments, Git commits, pull requests, ADRs, and canonical engineering documentation are written in professional English.
- Russian explanations are supporting material for the product owner and are not a second engineering source of truth.
- The agent works on task branches and must not directly modify protected `develop` or `main`.
- Technical implementation can be delegated to the AI; product and high-impact decisions remain with the user unless explicitly delegated.
- Every important change is verified before integration.
- New knowledge is treated as candidate knowledge until validated.
- A known-good local Aegis version remains usable when GitHub or the internet is unavailable.
- The agent must verify the actual technology versions used by a project before implementing against version-sensitive APIs or behavior.
- AI provider and model selection remains explicitly controlled by the user.

## AI backends

Aegis is intentionally model-agnostic. The default backend registry describes explicitly classified providers without ranking them or selecting a preferred model:

- OpenAI / Codex;
- Anthropic / Claude Code;
- Google / Gemini CLI;
- Meta / Muse Code and Model API;
- xAI / Grok API;
- Ollama / local model runtime.

Subscription login and direct API access are represented as separate connection modes. API credentials never belong in the repository.

See `docs/architecture/ai-backends.md` and `templates/ai-profiles.example.json` for the provider contract and user-selectable profile format.

## Managed project execution

The first executable project workflow is the managed Aegis/OpenHands coordinator. It requires a stable work-item ID, starts from an autonomous `ai/*` base branch, runs the verified local runtime preflight, executes one task through OpenHands, and verifies that OpenHands did not change Git HEAD or create a commit.

Example from the Aegis checkout:

    python3 tools/aegis_orchestrator.py \\
      /path/to/project \\
      51 \\
      "Implement the requested change." \\
      --agent-server-url http://127.0.0.1:8000 \\
      --container-workspace /projects/my-project \\
      --base-branch ai/integration \\
      --profile-config templates/ai-profiles.example.json \\
      --profile-name development-local \\
      --evidence-path /tmp/aegis-execution.json

The coordinator never commits, pushes, switches branches, resets, rebases, or silently changes providers/models. A successful run leaves the task changes uncommitted on the generated `ai/feature/<work-item>-execution` branch for Aegis review and Git hygiene.

After execution reaches `verification`, run the project-declared quality gates with `python3 tools/quality_gates.py /path/to/project`. The manifest lives at `.aegis/quality-gates.json`; the example contract is `templates/quality-gates.example.json`. With explicit work-item synchronization, all required gates passing advances `verification -> review`; a required failure advances `verification -> blocked`.

For explicit work-item synchronization, provide `--work-item-repository OWNER/REPO`. The work item must already be `ready`; Aegis then records the task branch, moves it to `in_progress`, and after successful OpenHands execution plus Git verification moves it to `verification`. Execution failures after `in_progress` are recorded as `blocked`. Omit the option to use the coordinator without external work-item mutations.

## Repository structure

- `00-constitution/` — non-negotiable operating rules.
- `01-orchestrator/` — autonomous execution model.
- `02-roles/` — role responsibilities.
- `03-workflows/` — repeatable engineering workflows.
- `skills/` — canonical reusable skills.
- `05-quality-gates/` — verification requirements.
- `06-git-github/` — Git and GitHub governance.
- `07-knowledge/` — knowledge lifecycle and evidence.
- `08-offline/` — offline and update strategy.
- `templates/` — files copied or generated into projects.
- `tools/` — local validation and project bootstrap tooling.
- `.agents/skills/` — Aegis repository-local skills recognized by OpenHands.

See `docs/architecture/overview.md` for the current system design.


## Pull-request delivery

After quality verification places a work item in \`review\`, use \`tools/delivery.py\` to create or reuse an explicit PR from the task branch into \`ai/integration\`:

    python3 tools/delivery.py create OWNER/REPO 60 ai/feature/60-execution ai/integration "feat: implement task" --body "Closes #60."

The delivery bridge verifies the resulting PR and attaches its URL to the work item. It never approves or merges.

After an actual merge, synchronize the delivery state:

    python3 tools/delivery.py sync-merge OWNER/REPO 60 123 ai/feature/60-execution ai/integration

Only a verified merged PR advances the work item from \`review\` to \`integration\`.


## Promotion readiness

Before promoting \`ai/integration\`, run the read-only verifier against the explicit protected target:

    python3 tools/promotion_readiness.py OWNER/REPO develop --workflow .github/workflows/validate.yml

For a release target:

    python3 tools/promotion_readiness.py OWNER/REPO main --workflow .github/workflows/validate.yml

The verifier checks fresh source/target SHAs, compare divergence, protection state, and a successful \`Aegis Validation\` run for the exact \`ai/integration\` SHA. Exit code \`0\` means no readiness blockers were observed; exit code \`2\` means the observed state is not ready.

The verifier is read-only and does not create, merge, or promote anything.

## Promotion snapshot preparation

When promotion readiness passes, prepare an owner-controlled promotion artifact:

    python3 tools/promotion_snapshot.py OWNER/REPO 66 main

The command creates or reuses ai/66-main-promotion, prepares a verified two-parent snapshot commit, and creates or reuses a draft pull request into main. Use --ready only when the promotion pull request should be created as ready for review.

The snapshot tool refuses develop while the selected target is behind or diverged. It never resolves conflicts and never approves or merges protected branches.

See docs/architecture/promotion.md for the complete contract.

## Release readiness

After changes reach main, evaluate release readiness without changing the repository:

    python3 tools/release_readiness.py OWNER/REPO

Exit code 0 means all release evidence is present. Exit code 2 means the release is blocked and the JSON result lists the observed blockers.

The verifier checks the exact main SHA, branch protection, exact-SHA Aegis Validation, version consistency across release metadata, and CHANGELOG state. It never creates tags, GitHub Releases, commits, branches, or pull requests.

See docs/architecture/release.md and skills/workflows/release-preparation/SKILL.md.

## Promotion merge synchronization

After a promotion PR is merged by the owner, synchronize the work item:

    python3 tools/promotion_sync.py OWNER/REPO 66 123 main

The command verifies the actual merged PR, protected target, merge commit ancestry, and then advances the work item from integration to done. An open or unmerged PR changes nothing. The tool never approves or merges.

## Autonomous integration merge

After a task PR reaches review and its checks are clean, Aegis may merge it into ai/integration:

    python3 tools/integration_merge.py OWNER/REPO 75 74

The tool verifies the work item, target branch, exact task branch, clean merge state, exact head SHA, and final merge commit before moving the work item from review to integration. It is never permitted to merge develop or main.

## Composed integration delivery

For a reviewed work item, use the composed delivery boundary:

    python3 tools/integration_delivery.py OWNER/REPO 77 ai/feature/77-integration "feat: deliver work item"

The controller creates or reuses the ai/integration task PR, requires successful validation for its exact head SHA, and then delegates the protected ai/integration merge. It never targets develop or main.



## Knowledge-gap candidate registry

When Aegis discovers a reusable knowledge gap, create a candidate record instead of modifying active skills:

    python3 tools/knowledge_gap.py create --scope global --capability "Missing database rollback guidance" --problem "Aegis lacks verified rollback guidance." --proposed-change "Create candidate guidance after a focused scenario." --reference https://example.com/authoritative-source

After a focused scenario passes, validate the candidate with explicit evidence:

    python3 tools/knowledge_gap.py validate .aegis/knowledge/candidates/CANDIDATE_ID.json --scenario "Run the documented rollback scenario" --evidence-ref https://ci.example.com/runs/123

The candidate registry never edits the active skill registry. A validated candidate remains a candidate until a separate controlled promotion step accepts it as known-good or active.

See docs/architecture/knowledge.md for the knowledge safety contract.

## Security review

Run the read-only repository security review before high-impact integration or promotion:

    python3 tools/security_review.py /path/to/repository

Exit code 0 means no high-severity findings were observed. Exit code 2 means blocking findings are present. The review never modifies the repository.
