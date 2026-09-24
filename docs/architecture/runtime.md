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

Until that verification exists, Aegis may validate the local model runtime and prepare an execution profile, but it must not claim that autonomous end-to-end execution has been proven.

## Failure handling

A failed preflight is a hard stop for local runtime execution.

The failure must identify:

- which provider and surface were selected;
- which model was expected;
- which endpoint failed, when applicable;
- whether the runtime was unreachable, malformed, or missing the exact model.

Automatic fallback is prohibited.

## Evidence

Runtime evidence is an observation, not a promise.

Aegis must distinguish:

- configured profile;
- verified local runtime state;
- actual OpenHands execution state.

A successful preflight proves that the selected local runtime is reachable and that the exact model tag is installed. It does not prove that OpenHands can execute a task successfully with that model.
