# OpenHands Execution Adapter Contract

## Purpose

\`tools/openhands_execution.py\` is the first programmatic execution boundary between Aegis and a local OpenHands Agent Server.

The adapter is intentionally narrower than the orchestration layer. It executes one explicitly selected task and returns execution evidence. It does not choose a provider, select a model, prepare a project mount, approve a risky action, or silently retry through another backend.

## Supported runtime boundary

The adapter is pinned to the OpenHands Agent Server contract verified for version \`1.49.5\`.

The server URL must be explicit and loopback-only (\`localhost\`, \`127.0.0.1\`, or \`::1\`). The adapter verifies \`/alive\`, \`/ready\`, and \`/server_info\` before creating a conversation and requires the reported Agent Server version and \`conversation_runtime=local\` to match the expected contract.

The local LLM agent payload must use the OpenHands \`Agent\` kind and an OpenAI-compatible model identifier such as \`openai/gemma4:31b\`. The configured LLM base URL and API key/placeholder are passed through unchanged; the adapter never prints them.

## Execution sequence

A single execution follows this order:

1. Validate the request, including the loopback server URL, explicit confirmation policy, absolute workspace, and agent payload.
2. Verify Agent Server liveness, readiness, and version contract.
3. \`POST /api/conversations\` with the selected agent, workspace, iteration limit, stuck detection, and confirmation policy.
4. \`POST /api/conversations/{id}/events\` with a user text message and \`run=false\`.
5. \`POST /api/conversations/{id}/run\` to start execution explicitly.
6. Poll \`GET /api/conversations/{id}\` until a stable terminal state or an approval/pause state is reached.
7. Retrieve all execution events through \`GET /api/conversations/{id}/events/search\` with pagination.
8. Return the conversation ID, final/blocking state snapshot, outcome classification, and event evidence.

The run trigger accepts the \`409 Conflict\` response documented by the installed SDK as an indication that the conversation is already running.

## Response-size safety

Every OpenHands JSON response is bounded to 1 MiB and parsed through the shared strict JSON object contract before interpretation. Duplicate object keys and non-standard JSON constants are rejected; a larger body is rejected as a transport/resource error rather than being loaded into memory as an unbounded Python object.

Event history retrieval is additionally bounded to 100 pages and 10,000 accumulated events. A history that exceeds either boundary is rejected rather than being returned as incomplete execution evidence.

Every OpenHands JSON response is bounded to 1 MiB before JSON parsing. A larger body is rejected as a transport/resource error rather than being loaded into memory as an unbounded Python object.

## State handling

The OpenHands Agent Server defines \`finished\`, \`error\`, and \`stuck\` as terminal execution states.

\`waiting_for_confirmation\` and \`paused\` are treated by Aegis as blocked outcomes. The adapter does not attempt to confirm, resume, or otherwise bypass that boundary. The caller must surface the state to the Aegis authority/escalation layer.

\`idle\`, \`running\`, and \`deleting\` are not successful completion states. An unknown state is a hard failure rather than something the adapter guesses how to handle.

The adapter requires two consecutive matching observations for a terminal status before returning. This reduces the chance of accepting a transient \`finished\` observation before server-side stop processing changes the state again.

## Workspace boundary

The \`workspace\` field is a path in the OpenHands server/container namespace, not an arbitrary host path.

By default the adapter allows only project paths below \`/projects\` and rejects:

- relative paths;
- the workspace root itself;
- parent traversal components;
- paths outside the configured root.

Aegis must therefore establish the host-to-container project mapping separately. This adapter does not invent a mount mapping or access host files on behalf of OpenHands.

## Canonical provenance

The low-level `OpenHandsExecutionResult` can be adapted through `openhands_execution_evidence` in `tools/evidence_adapters.py`.

The adapter is downstream of the existing execution redaction boundary. It does not execute requests, rerun conversations, inspect credentials, or mutate Git state. Finished maps to canonical `verified`; error, stuck, and blocked outcomes map to `failed` with explicit uncertainty.

Canonical provenance removes secret-like mapping keys before shared evidence validation. This is an evidence-format safety measure and does not change the original execution result.

## Authentication and evidence

When an Agent Server session API key is configured, it is sent as \`X-Session-API-Key\` on adapter requests. The key is not included in exceptions or returned execution evidence.

Execution events may contain project content or other sensitive task data. The adapter keeps them in memory and returns them to the caller; persistence and redaction policy remain an Aegis-layer responsibility.

## Failure recovery

A conversation is deliberately not deleted automatically after execution. If a timeout or transport error occurs after conversation creation, \`OpenHandsExecutionError.conversation_id\` preserves the identifier needed for inspection or recovery.

The adapter performs no provider fallback and no automatic model substitution.

## Verification boundary

Unit tests use an injected transport and do not require a live OpenHands installation. They verify request ordering, explicit \`run=false\`, authentication propagation, version gating, terminal and blocked states, timeout recovery, workspace validation, \`409\` run handling, and malformed event pagination.

Passing these tests proves the adapter's local implementation contract. It does not prove that a real OpenHands instance can successfully complete an engineering task. Live end-to-end execution remains a separate verification milestone.
