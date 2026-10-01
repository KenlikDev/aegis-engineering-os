# Aegis Runtime Boundary

Aegis separates engineering orchestration from model execution.

## Responsibilities

Aegis is responsible for:

- requirements and work-item control;
- role and skill selection;
- technology and repository state verification;
- quality gates;
- user decision and escalation boundaries;
- selection of the explicitly configured AI profile;
- runtime preflight evidence.

OpenHands is responsible for:

- executing the selected agent runtime;
- operating on the target workspace through its supported execution interface;
- returning execution results and failures to the Aegis orchestration layer.

The selected provider remains explicit. Aegis must never silently switch to another provider or model after a runtime failure.

## Runtime preflight

For the local Ollama path, Aegis performs a read-only preflight before execution:

1. Load and validate the selected AI profile.
2. Resolve the provider surface.
3. Verify the Ollama version endpoint.
4. List locally available models.
5. Require an exact match for the selected model tag.
6. Emit machine-readable evidence containing the selected profile, provider, surface, integration, connection mode, model, endpoint, runtime version, and exact availability result.

Run:

    python3 tools/preflight_runtime.py templates/ai-profiles.example.json development-local

The preflight does not pull models, change Ollama state, modify the project, or invoke an OpenHands execution command.

Ollama documents model names as model:tag values, the local-model listing at GET /api/tags, and runtime version reporting at GET /api/version. The exact model tag therefore remains part of the runtime evidence instead of being inferred from a mutable latest alias.

## Local HTTP response bounds

Local runtime JSON responses are parsed through the shared strict JSON object contract as well as the runtime-specific 1 MiB transport bound. Duplicate object keys and non-standard JSON constants are rejected before runtime facts are interpreted. The larger runtime bound is explicit and does not weaken the canonical evidence 65,536-byte persistence bound.

The local Ollama and OpenHands JSON clients enforce a 1 MiB maximum response body. They read at most one byte beyond the limit and fail closed before JSON parsing when the boundary is exceeded.

This bound applies to liveness, readiness, version, settings, conversation state, event-search, and model-list responses. It limits resource consumption without changing endpoint semantics or authentication behavior.

OpenHands event pagination also has explicit page and accumulated-event limits. Excessive histories fail closed instead of being partially accepted.

## OpenHands boundary

The runtime preflight deliberately does not hard-code an OpenHands CLI command.

OpenHands integration details can change independently from Aegis orchestration. A provider/runtime adapter must be verified against the exact installed OpenHands version before an execution command is promoted into the canonical runtime contract.

The current adapter is an explicit REST contract for the verified OpenHands Agent Server 1.49.5 runtime. It is implemented separately in \`tools/openhands_execution.py\` and documented in \`docs/architecture/openhands-execution.md\`.

Until a live execution has been verified, Aegis must not claim that autonomous end-to-end execution has been proven.

## OpenHands execution adapter

After the read-only preflight succeeds, the execution adapter can drive one explicitly selected task through the Agent Server:

1. verify \`/alive\`, \`/ready\`, and the exact Agent Server version;
2. create a conversation with the selected agent and OpenHands server-visible workspace;
3. send the user task with \`run=false\`;
4. trigger the run through the dedicated \`/run\` endpoint;
5. poll the authoritative conversation state;
6. stop on a stable terminal state or escalate \`waiting_for_confirmation\` / \`paused\`;
7. collect the complete paginated event history as execution evidence.

The adapter is loopback-only for the local runtime, never performs provider fallback, never substitutes a model, and never automatically confirms or resumes a blocked conversation.

The workspace is a path in the OpenHands container/server namespace. Aegis must establish the host-to-container mapping before execution; the adapter does not invent or mutate Docker mounts.

An execution timeout preserves the conversation ID in \`OpenHandsExecutionError\` so the caller can inspect or recover the existing conversation instead of creating an untracked duplicate.

The adapter requires an explicit confirmation policy rather than inheriting the OpenHands default implicitly. This keeps approval behavior visible at the Aegis authority boundary.

## Failure handling

A failed preflight is a hard stop for local runtime execution.

The failure must identify:

- which provider and surface were selected;
- which model was expected;
- which endpoint failed, when applicable;
- whether the runtime was unreachable, malformed, or missing the exact model.

Automatic fallback is prohibited.

For execution failures, preserve the OpenHands conversation identifier when one exists. Do not silently start another conversation with a different provider, model, or workspace.

## Evidence

Runtime evidence is an observation, not a promise.

Aegis must distinguish:

- configured profile;
- verified local runtime state;
- actual OpenHands execution state;
- final project/workspace verification after execution.

A successful preflight proves that the selected local runtime is reachable and that the exact model tag is installed. The execution adapter tests prove its HTTP/state contract. Neither one by itself proves that a real engineering task completed successfully against the live workspace.

## OpenHands Agent Server preflight

When the local OpenHands Agent Server is available, the same preflight can verify the execution boundary without assuming a default port. The URL is a local trust-boundary input and must be loopback-only (localhost, 127.0.0.1, or ::1) with no embedded credentials, query, or fragment.

Provide the exact server URL explicitly:

    python3 tools/preflight_runtime.py templates/ai-profiles.example.json development-local --agent-server-url "$AEGIS_OPENHANDS_AGENT_SERVER_URL"

The preflight reads:

- /alive to verify liveness;
- /ready to verify completed initialization;
- /server_info to capture the reported Agent Server, SDK, tools, workspace versions, and local conversation runtime;
- /api/settings to verify the active OpenHands agent configuration, including the exact selected model, the LLM base URL, and the presence of the configured LLM API key.

The /api/settings check is read-only. The selected local model is accepted only when the active OpenHands LLM model is exactly \`openai/<model-tag>\`, its base URL is the validated Docker-to-host Ollama endpoint, and an LLM API key is configured. The key value itself is never read into Aegis evidence.

A session API key may be supplied to authenticated Agent Server APIs through the environment; the key is never printed in evidence.

A reachable but not-ready server or a server that does not expose the selected model is a hard failure. The runtime URL is never inferred from a default port.

This still does not execute \`/v1/chat/completions\`, create conversations, or modify OpenHands settings.

## Managed project execution coordinator

The executable coordinator is `tools/aegis_orchestrator.py`. It is the first orchestration layer above the verified OpenHands adapter.

Before execution it verifies the target is a Git repository root, refuses a dirty worktree and protected branches, validates the explicit OpenHands container workspace, runs the existing read-only runtime preflight, and renders the explicitly selected local Ollama profile.

It then creates a task branch under the `ai/<kind>/` namespace and sends OpenHands a boundary-wrapped task. The task explicitly leaves commits, pushes, branch changes, resets, rebases, credential access, GitHub access, and sibling-repository access under Aegis control.

After OpenHands reports `finished`, the coordinator verifies:

- the task branch is still checked out;
- Git HEAD is unchanged from the branch creation checkpoint;
- the working tree contains inspectable changes unless `--allow-no-change` was explicitly supplied;
- `git diff --check` passes.

The coordinator does not automatically commit, push, create a pull request, merge, or discard a failed execution workspace. A failed execution therefore remains inspectable for recovery and diagnosis.

The container workspace path is explicit because the OpenHands adapter operates in the Agent Server/container namespace. Aegis does not infer Docker mounts. The local installation must establish the corresponding host-to-container mapping before the coordinator is used.

## Managed execution and work-item lifecycle

The managed coordinator can compose with the provider-neutral work-item contract from `tools/work_item_lifecycle.py`. Synchronization is optional and must be explicitly supplied by the caller.

When a provider is enabled, execution requires the work item to be in `ready` before the task branch is created. Aegis then records the branch traceability and transitions `ready -> in_progress`. This mutation order keeps a newly created branch from being presented as active work unless the provider has accepted the traceability record.

After OpenHands reaches `finished` and the Git post-execution integrity checks pass, Aegis records the OpenHands conversation and optional evidence reference, then transitions `in_progress -> verification`. It deliberately stops at `verification`: project-specific tests, review, integration, and completion remain separate quality/work-item stages.

If OpenHands raises an execution error, returns a non-finished outcome, or violates the post-execution Git boundary, Aegis attempts `in_progress -> blocked` and records only safe failure metadata (failure class, optional conversation ID, and outcome). The exception text itself is not copied to the external work item.

If provider synchronization itself fails, Aegis does not guess the remote state or perform an automatic compensating transition. The operation fails and the repository/task branch remains available for diagnosis.

For GitHub Issues, the lifecycle adapter maps a closed unlabeled issue to `done`, while open unlabeled issues remain `intake`. Explicit Aegis status labels remain authoritative when present.


## Promotion readiness boundary

The runtime layer ends before protected-branch promotion. \`tools/promotion_readiness.py\` is a read-only release gate that consumes current GitHub state and does not mutate any branch or pull request.

A promotion is considered ready only when \`ai/integration\` is protected, the selected protected target (\`develop\` or \`main\`) is protected, the source is ahead of the target without being behind it, and the exact current source SHA has a successful \`Aegis Validation\` run.

This evidence is intentionally separate from merge authorization. Human-controlled protected-branch delivery remains the final authority.
