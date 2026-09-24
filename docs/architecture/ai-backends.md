# AI Backend Architecture

Aegis is model-agnostic. The engineering workflow, governance, quality gates, and project state must not depend on one model vendor.

## Provider policy

The default backend registry contains explicitly classified US-origin cloud providers and a LOCAL Ollama backend:

- OpenAI;
- Anthropic;
- Google;
- Meta;
- xAI;
- Ollama (LOCAL).

The registry does not rank providers or models and never chooses a preferred model.

## Connection modes

A connection mode describes how the provider credential is obtained:

- `subscription_login` — authenticate through the provider's supported account/session flow. Usage is constrained by the applicable plan and provider limits.
- `api_key` — authenticate with an API key. Usage is governed by that API's pricing and rate limits.

These modes are intentionally distinct. A consumer subscription does not imply free API usage.

## Local Ollama

Ollama is a first-class LOCAL provider. A profile records the exact local model tag, such as `gemma4:31b`, and Aegis must verify that model is actually available locally before activation. The default local endpoint is `http://127.0.0.1:11434`; an environment-specific endpoint may be used when explicitly configured.

OpenHands exposes Ollama-specific LLM configuration through its LLM settings, and its SDK models the local endpoint as `ollama_base_url`.

## Current provider surfaces

| Provider | Surface | OpenHands path | Login/API mode |
| --- | --- | --- | --- |
| OpenAI | Codex | Built-in ACP | ChatGPT login or API key |
| Anthropic | Claude Code | Built-in ACP | Claude Pro/Max login or API key |
| Google | Gemini CLI | Built-in ACP | Google login or API key |
| Meta | Muse Code | Custom agent boundary | Meta subscription login or API key |
| Meta | Model API / Muse Spark | OpenAI-compatible LLM | API key |
| xAI | Grok API | OpenAI/LiteLLM-compatible LLM | API key |
| Ollama | Local | Ollama LLM | Local |

OpenHands currently documents built-in ACP support for Claude Code, Codex, and Gemini CLI. Other agent surfaces must use a compatible custom agent/adapter or the OpenHands LLM interface.

Meta documents Muse Code browser sign-in/API-key authentication and a separate Model API at `https://api.meta.ai/v1`. Model API usage is pay-as-you-go, while Muse Code also offers flat monthly subscriptions.

References:
- https://github.com/OpenHands/OpenHands/blob/main/docs/ACP_AGENTS.md
- https://github.com/OpenHands/software-agent-sdk
- https://dev.meta.ai/docs/overview
- https://dev.meta.ai/docs/muse-code
- https://dev.meta.ai/docs/pricing-rate-limits
- https://x.ai/api

## User-selected profiles

A project may keep an explicit profile file based on `templates/ai-profiles.example.json`.

Validate it:

    python tools/validate_ai_config.py path/to/ai-profiles.json

Render the selected profile into OpenHands-oriented settings:

    python tools/render_openhands_profile.py path/to/ai-profiles.json development

A profile selects the provider, surface, model, and connection mode. Aegis does not silently switch providers after a quota error, network failure, or model failure.

For ACP surfaces, `model` may be null because the external agent can expose or default its model. For OpenHands OpenAI-compatible transport, the model must be explicit.

## Secrets

Never commit API keys, OAuth tokens, session databases, or provider credentials.

For API-key profiles, the registry records only the expected environment variable name. The actual secret remains in the shell, credential manager, OpenHands secret store, or provider login.

## OpenHands boundary

The registry is declarative. It does not assume that every provider has native ACP support.

OpenHands exposes an LLM interface with a model, API key, and custom base URL, which allows compatible endpoints to be integrated without pretending they are native ACP agents.

## Model choice

The owner chooses which profile and model to use for each task. Aegis may validate configuration, render settings, report compatibility, and record the selected backend in task evidence, but it must not rank providers or make an implicit choice.
