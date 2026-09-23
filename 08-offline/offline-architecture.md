# Offline and Update Architecture

Aegis uses GitHub as the central coordination point while maintaining a local operational copy.

## Architecture

GitHub -> local mirror -> candidate -> active known-good -> OpenHands -> local LLM

## Session pinning

At session start, record the active Aegis version and commit SHA. Do not switch active instructions in the middle of a session.

## Update flow

fetch -> candidate -> validate -> promote -> active

A failed candidate must leave the existing active version untouched.

## Offline flow

When internet access is unavailable:
- continue using the local active known-good version;
- use local project source and local dependency caches;
- use cached documentation where available;
- mark externally dependent checks as pending.

## Recovery

When connectivity returns, synchronize remote state and process pending external verification before promoting new knowledge.
