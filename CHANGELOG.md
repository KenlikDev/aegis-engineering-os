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
- add regression coverage for bootstrap ownership and dirty-source rejection.

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
