# CI Remediation Architecture

## Purpose

CI remediation begins with evidence collection, not automatic changes.

tools/ci_diagnosis.py is the read-only diagnostic boundary. It reads workflow-run metadata, job state, failed step names, and bounded logs, then applies deterministic classification rules. GitHub job-log downloads are bounded before decoding; the evidence excerpt limit is a separate downstream bound.

## Evidence model

The report preserves:

- repository identity;
- workflow run id and URL;
- workflow path and event;
- head branch and SHA;
- job state;
- failed step name;
- bounded, redacted evidence;
- deterministic category and severity.

No credential value belongs in the report.

## Canonical provenance

The read-only diagnosis can emit its existing result into the canonical evidence envelope with `--canonical-evidence-output`.

The adapter preserves:

- workflow run identity, URL, workflow path, event, branch, and exact head SHA;
- job identity and state;
- failed step names;
- deterministic category, severity, actionability, message, and bounded redacted evidence;
- the full diagnosis status and summary.

Canonical status mapping is explicit:

- healthy -> `verified`;
- diagnosed -> `failed`;
- inconclusive -> `unknown`.

An inconclusive result records explicit uncertainty and is never upgraded to a verified root cause.

## Diagnosis semantics

Supported signatures are intentionally narrow. The tool may report:

- ci-permission;
- timeout;
- security-review;
- repository-structure;
- source-syntax;
- test-failure;
- bootstrap-failure;
- unknown.

An unknown failure is inconclusive; Aegis must not invent a root cause from incomplete evidence.

## GitHub boundary

The GitHub adapter is read-only. Workflow-run and job metadata are read through the versioned GitHub REST API. Job logs are downloaded through GitHub's redirect-based log endpoint; the redirect handler strips the GitHub Authorization header before following a cross-host HTTPS download. The response body is limited to 1 MiB plus one sentinel byte before decoding. Oversized logs are rejected rather than partially interpreted.

The adapter cannot rerun, cancel, dispatch, approve, merge, or edit workflows.

## Lifecycle

failure
-> exact run verification
-> failed job discovery
-> failed step discovery
-> bounded log evidence
-> deterministic classification
-> remediation work item

CI diagnosis is therefore a precursor to engineering remediation, not remediation itself.


## GitHub credential destination

CI diagnosis sends bearer credentials only to the exact `https://api.github.com` origin. The API client rejects arbitrary HTTPS hosts, non-root paths, URL credentials, queries, and fragments. This keeps CI diagnosis aligned with the repository-wide GitHub credential destination boundary.


The CI diagnosis GitHub API transport uses the shared one-mebibyte response bound. Job logs have their own one-mebibyte download boundary before text decoding because signed log redirects are handled separately and without GitHub credentials.
