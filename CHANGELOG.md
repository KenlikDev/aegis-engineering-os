# Changelog

All notable changes to Aegis Engineering OS will be documented here.

## Unreleased

- add provider-neutral AI backend registry for OpenAI, Anthropic, Google, Meta, xAI, and local Ollama;
- add explicit user-selected AI profiles without automatic provider fallback;
- distinguish subscription login from direct API authentication and billing;
- model provider surfaces individually so subscription/API modes cannot be confused;
- render user-selected profiles into OpenHands-oriented settings;
- document Meta Muse Code and Model API as separate connection paths;
- add AI backend configuration validation and regression coverage;
- make bootstrap state deterministic and self-describing;
- reconcile previously managed skills when changing presets;
- protect unowned and customized project skills from overwrite;
- add transactional bootstrap staging and rollback;
- require clean Aegis source provenance and record it in state;
- add offline project integrity verification with per-skill SHA-256 checksums;
- validate source metadata before installation;
- add regression coverage for bootstrap ownership and dirty-source rejection;
- add the OpenHands Agent Server execution adapter contract with exact version gating, explicit task execution sequencing, and execution evidence collection;
- add the managed project execution coordinator with work-item branch safety, runtime preflight reuse, OpenHands boundary prompts, and post-execution Git integrity checks;
- add the executable provider-neutral work-item lifecycle bridge with GitHub Issues persistence, optimistic state checks, blocked-state resume metadata, traceability comments, and read-after-write verification;
- compose managed OpenHands execution with explicit work-item lifecycle synchronization, safe failure blocking, and verification-stage traceability;
- add the executable project quality-gate runner with explicit manifest commands, bounded redacted evidence, and verification-to-review/blocked lifecycle synchronization.

## 0.1.0-alpha.1

Initial experimental foundation:
- constitution and agent operating rules;
- orchestrator workflow;
- product discovery and delegated idea selection;
- user decision model;
- version verification;
- Git and GitHub hygiene;
- offline operation model;
- knowledge lifecycle;
- project bootstrap templates;
- repository validation scaffold.

- add the read-only promotion readiness verifier for ai/integration -> develop/main, including exact-SHA CI evidence and protection checks;
- add the owner-controlled promotion snapshot bridge, which prepares an exact integration-tree snapshot on a short-lived target-based branch and opens or reuses a draft promotion pull request without merging protected branches;
- add the read-only release readiness verifier and release-preparation workflow for protected main;
- guarantee an explicit validation path after merged pull requests, including the actual merge commit for ai/integration, with event-isolated concurrency so the exact integration push validation is not cancelled;
