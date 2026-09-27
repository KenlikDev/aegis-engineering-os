# Local Aegis Installation for OpenHands

## Goal

Keep Aegis in a local Git clone, pin a known-good version, and install selected skills into each target project under .agents/skills/.

OpenHands recognizes project-local AGENTS.md and skills under .agents/skills/ when they are present in the project workspace.

## Verified local OpenHands runtime

The validated local setup uses:

- OpenHands Agent Canvas image: `ghcr.io/openhands/agent-canvas:1.23.0`;
- unified local entry point: `127.0.0.1:8000`;
- OpenHands Agent Server: `1.49.5`;
- Ollama: `0.34.3`;
- local model: `gemma4:31b`.

The container image runs its `openhands` user as UID/GID `10001:10001`. Bind-mounted state directories therefore must be accessible to that identity. The live smoke-test harness grants ACL access only on the unique temporary workspace it creates; it does not recursively change permissions on the existing workspace root.

Prepare the local directories:

    mkdir -p "$HOME/.openhands" "$HOME/openhands_workspace"
    sudo chown -R 10001:10001 "$HOME/.openhands" "$HOME/openhands_workspace"
    sudo chmod -R u+rwX,g+rwX "$HOME/.openhands" "$HOME/openhands_workspace"

Run OpenHands locally:

    docker run -d \
      --name openhands \
      --restart unless-stopped \
      --add-host host.docker.internal:host-gateway \
      -p 127.0.0.1:8000:8000 \
      -v "$HOME/.openhands:/home/openhands/.openhands" \
      -v "$HOME/openhands_workspace:/projects" \
      ghcr.io/openhands/agent-canvas:1.23.0

Open:

    http://127.0.0.1:8000/canvas

Keep the published port bound to 127.0.0.1 for a local-only installation.

## Ollama connection

For Dockerized OpenHands, do not use `127.0.0.1:11434` inside the container. Use the Docker host alias:

    http://host.docker.internal:11434/v1

OpenHands should use the OpenAI-compatible model identifier:

    openai/gemma4:31b

Use a non-secret placeholder API key such as:

    local-llm

Verify the network boundary:

    curl -sS http://127.0.0.1:11434/api/version
    ollama list
    docker exec openhands python -c 'import urllib.request; print(urllib.request.urlopen("http://host.docker.internal:11434/api/version", timeout=5).read().decode())'

The host-side Aegis preflight continues to use `http://127.0.0.1:11434` because that endpoint is used for direct Ollama evidence. The OpenHands container uses `host.docker.internal` because its `127.0.0.1` points to the container itself.

## Aegis preflight

Run the local Ollama and OpenHands Agent Server checks before claiming the runtime boundary is verified:

    python3 tools/preflight_runtime.py templates/ai-profiles.example.json development-local --agent-server-url http://127.0.0.1:8000

The preflight is read-only. It verifies the exact configured model, Ollama runtime version, Agent Server liveness/readiness, local conversation runtime, reported component versions, and the active OpenHands LLM settings exposed by `/api/settings`.

When the Agent Server requires authentication, provide its session key through the `AEGIS_OPENHANDS_AGENT_SERVER_API_KEY` environment variable. The key is used only for the request and is not emitted in evidence.

The preflight does not call `/v1/chat/completions`, create conversations, or modify OpenHands settings.

## Live Aegis-to-OpenHands smoke test

After the local runtime preflight is green, run the isolated live smoke test only from the Ubuntu VM that owns the OpenHands Docker workspace mount:

    python3 tools/live_e2e_smoke_test.py \
      templates/ai-profiles.example.json \
      development-local \
      --agent-server-url http://127.0.0.1:8000 \
      --host-workspace-root "$HOME/openhands_workspace"

The harness verifies the exact expected local runtime:

- Ollama 0.34.3;
- OpenHands Agent Server 1.49.5;
- `ghcr.io/openhands/agent-canvas:1.23.0`;
- local conversation runtime;
- selected model `gemma4:31b`.

It creates one unique temporary directory directly under `$HOME/openhands_workspace`, grants the OpenHands container UID `10001` ACL access only to that directory, maps it to `/projects/<name>`, allows OpenHands Agent Server to initialize its required `.git` metadata, asks the agent to create exactly `Aegis-Live-E2E.txt` with `AEGIS_LIVE_E2E_OK`, rejects any other top-level workspace entries, verifies the file from the host, emits machine-readable evidence, and then removes only the temporary directory it created.

The smoke test uses an explicit `NeverConfirm` policy only for this isolated temporary workspace. It does not grant general approval authority to Aegis and must not be reused as a general project-execution mechanism.

When the Agent Server requires authentication, the harness reads `AEGIS_OPENHANDS_AGENT_SERVER_API_KEY` by default, or the environment variable named by `--agent-server-api-key-env`.

A passing adapter unit test or CI run is not live evidence. End-to-end capability is considered verified only when this smoke test itself completes successfully on the target Ubuntu VM.

## Local clone

Clone this repository somewhere stable on the development VM, for example:

    ~/aegis-engineering-os

Do not place the only copy on a removable or disposable workspace.

## Bootstrap a project

From the Aegis repository:

    python3 tools/bootstrap_project.py /path/to/project --preset core

For product-discovery work:

    python3 tools/bootstrap_project.py /path/to/project --preset all

Aegis refuses to bootstrap the source repository itself or any target path inside the Aegis source tree. Use `--dry-run` before changing an unfamiliar project.

## Pinning and verification

After each deliberate Aegis update, the target project's .aegis/aegis-version.json records:

- the exact Aegis version and source commit;
- the fact that the source worktree was clean;
- the selected preset and effective integrations;
- the exact installed skill set;
- a SHA-256 checksum for every installed skill.

Changing presets during a later bootstrap removes only skills previously recorded as managed by Aegis, refuses to overwrite unowned project skills, and refuses to overwrite or delete customized managed skill directories. Project-local skills not recorded in Aegis state are left untouched.

Bootstrap stages changes before applying them and rolls back managed skills and state when a mutation fails.

Verify an installed project after recovery or when integrity is uncertain:

    python3 tools/verify_project.py /path/to/project

The verifier does not need network access or the Aegis source clone because it validates the installed files against the recorded checksums.

Do not replace the active Aegis knowledge during a running session.

## Offline operation

The local clone is the operational fallback. If GitHub or the internet becomes unavailable, continue using the last active known-good version.

External facts that cannot be verified offline must be marked pending and rechecked after connectivity returns.

## Update discipline

1. Fetch the Aegis repository when online.
2. Validate the candidate version.
3. Review changes.
4. Promote the candidate only after validation.
5. Pin new sessions to the promoted version.
6. Verify each bootstrapped project after recovery or an integrity-sensitive update.

Never replace the only known-good local copy with an unvalidated update.
