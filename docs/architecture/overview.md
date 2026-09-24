# Aegis Engineering OS Architecture

Aegis is a modular operating system for an autonomous software-development agent running with OpenHands and a local language model.

## Layers

### Constitution

Non-negotiable principles and authority boundaries.

### Orchestrator

Determines the work mode, selects skills, sequences workflows, and enforces quality gates.

### Roles

Define responsibilities such as product management, architecture, engineering, QA, security, and operations.

### Skills

Provide focused operational knowledge.

The canonical reusable library is stored under skills/. OpenHands-compatible project-local skills are installed under .agents/skills/.

### Knowledge

Stores validated guidance, candidates, references, decisions, and lessons.

### Runtime boundary

Separates Aegis orchestration from OpenHands execution. The local Ollama path has a read-only preflight that verifies the selected profile, runtime version, and exact installed model before execution is attempted.

### Governance

Defines user authority, Git and GitHub policy, version pinning, and offline behavior.

## Design goals

- modularity;
- progressive disclosure;
- reproducibility;
- offline continuity;
- clean Git history;
- explicit decision authority;
- self-improvement without silent global degradation;
- Russian user interaction with English engineering artifacts.

## Current maturity

Version 0.1.0-alpha.1 is experimental and is expected to change after validation on real repositories.
