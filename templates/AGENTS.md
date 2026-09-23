# Project Agent Instructions

This file is generated for a project using Aegis Engineering OS.

## Language

- Communicate with the project owner in Russian.
- Keep code, comments, commits, pull requests, ADRs, and canonical technical documentation in English.

## Aegis

Record the active Aegis version and commit SHA in the project Aegis manifest.

## Repository workflow

Work on ai/* task branches.

Target promotion flow:

ai/* -> ai/integration -> develop -> main

Never directly modify develop or main.

## Version verification

Before version-sensitive work, inspect the project's source-of-truth manifests and lockfiles and verify compatibility with the exact versions in use.

## Quality

Do not claim completion without running the applicable tests, lint/static analysis, build, and security checks.

## User interaction

Ask only product, business, security, privacy, cost, or irreversible-decision questions that genuinely require the owner's choice.
