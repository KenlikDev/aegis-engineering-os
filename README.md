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
      --work-item-kind feature \\
      --work-item-document /path/to/project/work-item.md \\
      --version-evidence-ref .aegis/version-evidence.json \\
      --architecture-not-required \\
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


## Lifecycle mutation provenance

Verified work-item lifecycle mutations can be adapted into canonical provenance through the `mutation_evidence` adapter. It records provider, operation, work-item identity, state transition, verification state, and reference without changing lifecycle behavior.

An unverified mutation remains canonical `unknown` with explicit read-after-write uncertainty.

## Promotion readiness

Before promoting \`ai/integration\`, run the read-only verifier against the explicit protected target:

    python3 tools/promotion_readiness.py OWNER/REPO develop --workflow .github/workflows/validate.yml

To additionally persist the assessment in the canonical provenance envelope:

    python3 tools/promotion_readiness.py OWNER/REPO develop --evidence-output /tmp/promotion-evidence.json

For a release target:

    python3 tools/promotion_readiness.py OWNER/REPO main --workflow .github/workflows/validate.yml

The verifier checks fresh source/target SHAs, compare divergence, protection state, and a successful \`Aegis Validation\` run for the exact \`ai/integration\` SHA. Exit code \`0\` means no readiness blockers were observed; exit code \`2\` means the observed state is not ready.

The verifier is read-only and does not create, merge, or promote anything.

## Promotion snapshot preparation

When promotion readiness passes, prepare an owner-controlled promotion artifact:

    python3 tools/promotion_snapshot.py OWNER/REPO 66 main

The command creates or reuses ai/66-main-promotion, prepares a verified two-parent snapshot commit, and creates or reuses a draft pull request into main. Use --ready only when the promotion pull request should be created as ready for review.

The snapshot tool refuses develop while the selected target is behind or diverged. It never resolves conflicts and never approves or merges protected branches.

The optional evidence artifact preserves the exact observed source SHA and validation provenance in the canonical evidence envelope.

See docs/architecture/promotion.md for the complete contract.

## Release readiness

After changes reach main, evaluate release readiness without changing the repository:

    python3 tools/release_readiness.py OWNER/REPO

    python3 tools/release_readiness.py OWNER/REPO --evidence-output /tmp/release-evidence.json

Exit code 0 means all release evidence is present. Exit code 2 means the release is blocked and the JSON result lists the observed blockers.

The verifier checks the exact main SHA, branch protection, exact-SHA Aegis Validation, version consistency across release metadata, and CHANGELOG state. It never creates tags, GitHub Releases, commits, branches, or pull requests.

The optional evidence artifact preserves the exact observed main SHA and validation provenance in the canonical evidence envelope.

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

A candidate record can also be adapted into canonical evidence. Candidate state is `pending`, validated state is `verified`, and rejected state is `failed`; canonical `verified` does not activate knowledge.

See docs/architecture/knowledge.md for the knowledge safety contract.

## Security review

Run the read-only repository security review before high-impact integration or promotion:

    python3 tools/security_review.py /path/to/repository

Exit code 0 means no high-severity findings were observed. Exit code 2 means blocking findings are present. The review never modifies the repository.

To additionally persist the deterministic review in the canonical provenance envelope:

    python3 tools/security_review.py /path/to/repository \
      --canonical-evidence-output /tmp/security-evidence.json \
      --revision <exact-repository-revision>

The canonical artifact preserves finding rule IDs, severity, paths, lines, and messages without introducing secret values.

See docs/architecture/security.md for the security-review architecture and safety boundary.


## CI remediation

Diagnose a failed GitHub Actions run without changing CI state:

    python3 tools/ci_diagnosis.py OWNER/REPO --run-id 123

Or inspect the latest run for a workflow and branch:

    python3 tools/ci_diagnosis.py OWNER/REPO --latest --workflow .github/workflows/validate.yml --branch ai/integration

Exit code 0 means the run was healthy or a deterministic diagnosis was produced. Exit code 2 means the failure is inconclusive. The tool never reruns, cancels, edits, approves, dispatches, or merges workflows.

To additionally persist the diagnosis in the canonical provenance envelope:

    python3 tools/ci_diagnosis.py OWNER/REPO --run-id 123 \
      --canonical-evidence-output /tmp/ci-diagnosis-evidence.json

The canonical artifact preserves the workflow run head SHA as its revision and maps healthy/diagnosed/inconclusive states to verified/failed/unknown.

See docs/architecture/ci-remediation.md for the evidence and safety contract.


## OpenHands execution provenance

The low-level OpenHands result can be adapted into canonical evidence through the `openhands_execution_evidence` adapter in `tools/evidence_adapters.py`. This is an additive record boundary; it does not execute OpenHands again.

Finished execution is canonical `verified`. Error, stuck, and blocked outcomes are canonical `failed` with explicit uncertainty. The adapter uses only the already-redacted execution state and events and removes secret-like keys before canonical validation.

See `docs/architecture/evidence-provenance.md` for the common provenance boundary.

## Evidence provenance

Material state observations use a provider-neutral evidence envelope with explicit provenance:

    python3 tools/state_verification.py record \
      /path/to/state-input.json \
      /path/to/state-evidence.json

Validate an existing evidence artifact before relying on it:

    python3 tools/state_verification.py validate \
      /path/to/state-evidence.json

The contract records the evidence kind, source, subject, revision, observation time, result, uncertainty, references, optional artifact hash, and a canonical self-hash. Recording and validation never mutate the observed system.

See docs/architecture/evidence-provenance.md and docs/governance/state-verification.md.


## Evidence bundles

Compose already validated canonical evidence artifacts into one deterministic reference set:

    python3 tools/evidence_bundle.py create \
      /path/to/project \
      .aegis/evidence-bundle.json \
      "Inputs for implementation readiness" \
      .aegis/state-evidence.json \
      .aegis/promotion-evidence.json

Validate the bundle and every referenced evidence artifact:

    python3 tools/evidence_bundle.py validate \
      /path/to/project \
      .aegis/evidence-bundle.json

Bundles do not infer completeness, upgrade evidence status, contact providers, or mutate observed systems.

See docs/architecture/evidence-bundles.md.

To validate a bundle against an explicit evidence-set contract:

    python3 tools/evidence_bundle_requirements.py \
      /path/to/project \
      /path/to/project/.aegis/evidence-bundle.json \
      /path/to/project/evidence-set-requirements.json

The requirements document explicitly declares the required `kind` values and optional exact `status`, `subject`, and `source` selectors. The consumer never infers requirements from bundle purpose or free-form text.


## Version verification evidence

After project discovery, record explicit version claims and pin their authoritative sources:

    python3 tools/version_verification.py record \
      /path/to/project \
      templates/version-claims.example.json

Validate the resulting evidence before implementation readiness:

    python3 tools/version_verification.py validate \
      /path/to/project \
      /path/to/project/.aegis/version-evidence.json

Optionally adapt the validated version inventory into the canonical provenance envelope:

    python3 tools/version_verification.py validate \
      /path/to/project \
      /path/to/project/.aegis/version-evidence.json \
      --revision <exact-project-revision> \
      --evidence-output /tmp/version-verification-evidence.json

When external compatibility verification is still pending, the canonical artifact remains `pending` and records that uncertainty explicitly. The tool never chooses versions or upgrades dependencies. It verifies explicit claims, source containment, source SHA-256, and the presence of each claimed version string.

See docs/architecture/version-verification.md.


## Implementation readiness

Before managed execution, evaluate the explicit implementation-readiness contract:

    python3 tools/implementation_readiness.py \\
      /path/to/project/work-item.md \\
      --project-root /path/to/project \\
      --kind feature \\
      --version-evidence-ref .aegis/version-evidence.json \\
      --architecture-not-required

The gate fails closed when requirements are blocked, the structured version-evidence artifact is missing or invalid, required architecture planning is blocked, or the authoritative work item is not ready.

Optionally persist the readiness result in the canonical provenance envelope:

    python3 tools/implementation_readiness.py \
      /path/to/project/work-item.md \
      --project-root /path/to/project \
      --kind feature \
      --version-evidence-ref .aegis/version-evidence.json \
      --architecture-not-required \
      --evidence-output /tmp/implementation-readiness-evidence.json

A ready result with pending external version compatibility remains canonical `pending`; blocked readiness is canonical `failed`.

See docs/architecture/implementation-readiness.md.


## Workflow composition

Build the deterministic workflow sequence for an explicitly classified work item:

    python3 tools/workflow_composition.py --kind refactoring

The composition layer validates every referenced capability against skills/registry.json, preserves conditional steps explicitly, and never infers the work-item kind from free-form text.

To additionally require an explicit canonical evidence set before managed implementation, both inputs must be supplied:

    python3 tools/implementation_readiness.py /path/to/project/work-item.md \
      --project-root /path/to/project \
      --kind feature \
      --version-evidence-ref .aegis/version-evidence.json \
      --architecture-not-required \
      --evidence-bundle .aegis/readiness-bundle.json \
      --evidence-set-requirements .aegis/readiness-requirements.json

The requirements document is the explicit source of evidence-set completeness. It may bind selectors to exact evidence revisions. The readiness gate records satisfaction or blocks on malformed/unsatisfied requirements; it does not infer selectors from free-form text or bundle purpose.

To additionally persist an explicit composition as canonical evidence:

    python3 tools/workflow_composition.py --kind refactoring \
      --canonical-evidence-output /tmp/workflow-evidence.json

See docs/architecture/workflow-composition.md.


## Requirements clarification

Check a work item before planning without inventing missing decisions:

    python3 tools/requirements_clarification.py path/to/work-item.md

Exit code 0 means the required inputs are present. Exit code 2 means blocker-level clarification questions remain. The workflow is read-only and does not alter the work item.

To additionally persist clarification as canonical evidence:

    python3 tools/requirements_clarification.py /path/to/work-item.md \
      --canonical-evidence-output /tmp/requirements-evidence.json

A complete requirements result is canonical `verified`; unresolved blocker questions remain canonical `failed`.

See docs/architecture/requirements.md for the decision-ownership contract.


## Architecture planning

Produce a deterministic, read-only architecture plan after requirements clarification:

    python3 tools/architecture_planning.py path/to/work-item.md

When lifecycle verification is required, pass the authoritative GitHub work item:

    GITHUB_TOKEN="$TOKEN" python3 tools/architecture_planning.py \
      path/to/work-item.md \
      --work-item-repository OWNER/REPO \
      --work-item-id 123

The planner separates explicit evidence, deterministic technical deductions, user-owned decisions, and blockers. It never changes source files, scope, Git state, or protected branches.

To additionally persist the architecture plan as canonical evidence:

    python3 tools/architecture_planning.py /path/to/work-item.md \
      --canonical-evidence-output /tmp/architecture-evidence.json

A ready plan is canonical `verified`; a blocked plan is canonical `failed`.

See docs/architecture/architecture-planning.md.


## Testing

Validate the project-declared testing and quality contract without inferring commands:

    python3 tools/testing.py /path/to/project --dry-run

Execute the explicit contract:

    python3 tools/testing.py /path/to/project

With lifecycle synchronization, the work item must already be in `verification`; required gates passing advances it through the existing quality-gate contract to `review`, while required failures block it.

To additionally persist the already-redacted testing result in the canonical provenance envelope:

    python3 tools/testing.py /path/to/project \
      --canonical-evidence-output /tmp/testing-evidence.json \
      --revision <exact-project-revision>

The canonical artifact records the explicit gate results without introducing another test runner.

See docs/architecture/testing.md.


## Refactoring

For behavior-preserving structural changes, use the controlled refactoring workflow. It establishes a verified baseline, applies the normal implementation boundary, repeats the explicit testing contract, and requires independent review focused on semantic preservation.

The workflow never invents behavior invariants or silently turns refactoring into feature work.

See docs/architecture/refactoring.md.
