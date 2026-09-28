# CI Remediation Architecture

## Purpose

CI remediation begins with evidence collection, not automatic changes.

tools/ci_diagnosis.py is the read-only diagnostic boundary. It reads workflow-run metadata, job state, failed step names, and bounded logs, then applies deterministic classification rules.

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

The GitHub adapter is read-only. Workflow-run and job metadata are read through the versioned GitHub REST API. Job logs are downloaded through GitHub's redirect-based log endpoint; the redirect handler strips the GitHub Authorization header before following a cross-host HTTPS download.

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
