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
6. Emit machine-readable evidence containing the provider, surface, integration, connection mode, model, endpoint, runtime version, and availability result.

Run:

    python3 tools/preflight_runtime.py templates/ai-profiles.example.json development-local

The preflight does not pull models, change Ollama state, modify the project, or invoke an OpenHands execution command.

Ollama documents model names as model:tag values, the local-model listing at GET /api/tags, and runtime version reporting at GET /api/version. The exact model tag therefore remains part of the runtime evidence instead of being inferred from a mutable latest alias.

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

When the local OpenHands Agent Server is available, the same preflight can verify the execution boundary without assuming a default port.

Provide the exact server URL explicitly:

    python3 tools/preflight_runtime.py templates/ai-profiles.example.json development-local --agent-server-url "$AEGIS_OPENHANDS_AGENT_SERVER_URL"

The preflight reads:

- /alive to verify liveness;
- /ready to verify completed initialization;
- /server_info to capture the reported Agent Server, SDK, tools, workspace versions, and local conversation runtime;
- /v1/models to verify that the exact selected model is exposed through OpenHands' OpenAI-compatible LLM surface.

The /v1/models check is read-only. The selected model is accepted when the server reports either the raw model tag or the OpenAI-compatible \`openai/<model-tag>\` identifier.

A session API key may be supplied to authenticated Agent Server APIs through the environment; the key is never printed in evidence.

A reachable but not-ready server or a server that does not expose the selected model is a hard failure. The runtime URL is never inferred from a default port.

This still does not execute \`/v1/chat/completions\`, create conversations, or modify OpenHands settings.
