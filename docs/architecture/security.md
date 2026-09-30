## Flow-sensitive limitations

The Python GitHub API-version review is intentionally conservative when headers are assigned through variables. Every executable assignment observed before a request sink must be compliant; an unknown or conditionally non-compliant assignment prevents the request from being treated as verified.

The review does not attempt to prove arbitrary Python control flow. This avoids allowing a later compliant assignment to mask an earlier reachable unsafe assignment.

## Workflow API-version sink boundary

For GitHub API calls implemented through executable GitHub Actions `run` blocks, the API-version header requirement is evaluated within the same `run` scalar as the API URL. An unrelated header string in another YAML field does not satisfy the request-level security rule.

Multiline `run: |` and folded `run: >` blocks are treated as one executable scalar for this check. This keeps the read-only review conservative without treating comments or unrelated configuration text as evidence that an executable request is compliant.

# Security Review Architecture

## Purpose

Security review is a read-only gate before integration or promotion.

It produces deterministic findings from observable repository state. A finding is evidence of a specific rule violation, not a statement that the whole repository is secure or insecure.

## Checks

tools/security_review.py reviews:

- GitHub Actions trust-boundary triggers;
- explicit workflow permissions;
- broad or unnecessary write permissions;
- third-party action pinning;
- GitHub API version headers;
- executable subprocess security;
- destructive Git operations;
- direct hardcoded writes to protected refs;
- high-confidence credential patterns.

## Severity model

High findings block the review. Medium findings are visible but do not block the review alone.

## Safety boundary

The review reads repository files only. It never changes code or configuration, creates issues, changes branches, modifies GitHub permissions, or prints matched credential values.

## Canonical provenance

The read-only review can emit its existing result into the canonical evidence envelope with `--canonical-evidence-output`. The adapter preserves finding rule IDs, severity, repository-relative paths, line numbers, messages, and the deterministic summary.

A review with any high-severity finding is canonical `failed`. A review without high-severity findings is canonical `verified`, while medium and low findings remain explicitly present in the result.

This output is additive and does not alter security-review findings or exit-code semantics.

## Lifecycle position

implementation
-> code review
-> security review
-> quality verification
-> integration

Security review can also be invoked before promotion when a high-impact change crosses a trust boundary.


## Network and filesystem boundaries

Local runtime preflight rejects HTTP redirects because it may send an Agent Server session authentication header to the selected local endpoint. Redirects therefore cannot silently move that header to another origin.

Security review inputs reject symbolic links, including broken symbolic links, in `.github/workflows`, `tools`, and `config`; a symlinked review root is also a hard failure. The review never resolves a repository input through a symbolic link before reading it. Managed bootstrap roots and skill paths reject symbolic links, including broken symbolic links, before mutation. The `.agents/skills` and `.aegis` roots are checked for symlinked ancestors and for resolved paths outside the project before state access or installation. When Aegis installs its own AGENTS.md, the project state records explicit ownership and a SHA-256 checksum; verification and subsequent bootstrap runs fail closed on tampering or symlink substitution. A pre-existing project-owned AGENTS.md remains unmanaged and is never overwritten or falsely attributed to Aegis. Legacy AGENTS ownership classification computes the observed file digest once and reuses that exact digest for the ownership decision, avoiding split-read provenance. Canonical evidence, quality-gate, version-verification, evidence-bundle, managed-execution, testing evidence, and bootstrap state writers reject symbolic-link destinations and persist JSON through atomic same-directory replacement anchored to the opened destination directory. Bootstrap managed `SKILL.md` and Aegis-owned `AGENTS.md` installation uses the same anchored no-follow filesystem boundary through an atomic byte-copy primitive, so a destination symlink introduced after preflight cannot redirect managed file content outside the project. Installation does not perform a separate path-based destination-directory creation step; the atomic writer is the sole destination-directory publication boundary. Managed execution validates its requested evidence output before creating a task branch or starting OpenHands. Bootstrap also captures the exact source HEAD before staging and verifies the same clean source checkpoint before state persistence, so installed skills and recorded source provenance cannot silently drift across a source checkout during one transaction. These checks preserve the declared filesystem and source provenance boundaries rather than relying on the final resolved path alone.


GitHub credential destination

GitHub API adapters may send bearer credentials only to the exact `https://api.github.com` origin. HTTPS alone is not sufficient: custom hosts, credentials in the URL, non-root paths, queries, and fragments are rejected. GitHub Enterprise endpoints must be introduced as an explicit provider policy rather than broadening this default credential destination.


Release-readiness and structural metadata validation use the shared strict JSON parser as well. Installed-project verification independently enforces the same strict state parsing and rejects symbolic-link state and managed skill topology before trusting recorded checksums. Duplicate object keys cannot satisfy or bypass repository version and release metadata checks through last-value-wins parser behavior.

The read-only CI diagnosis GitHub adapter follows the same credential destination policy: bearer credentials are sent only to the exact `https://api.github.com` origin. Its separate job-log redirect path deliberately strips credentials before following signed log URLs.


Release readiness follows the same GitHub credential destination policy as the other GitHub adapters: bearer credentials are restricted to the exact `https://api.github.com` origin.


## Security-review executable API-version header check

For Python sources, the GitHub API-version rule is evaluated after AST parsing and follows the executable request sink. A shared-header exemption is valid only when `github_api_headers()` reaches the same `Request(..., headers=...)` expression associated with a resolvable GitHub API URL. The analyzer follows direct URL literals and simple assigned/derived name aliases. A compliant request cannot mask a separate non-compliant GitHub request in the same file. Comments, docstrings, unused calls, and unused variables do not satisfy the control.

A direct `X-GitHub-Api-Version` exemption is valid only when the header appears in the executable request headers, either directly or through a simple assigned mapping that reaches `Request(..., headers=...)`. The shared `tools/github_http_security.py` module is a policy-definition surface rather than a GitHub API consumer, so the consumer rule intentionally excludes that exact path while reviewing all other Python sources.

For workflow files, the API-version check remains a textual workflow-level check because YAML is not executed by the Python AST analyzer. Workflows that reference `https://api.github.com` must also contain the explicit `X-GitHub-Api-Version` header. YAML comments do not satisfy this requirement; the check ignores comment text while preserving quoted content.

## GitHub REST transport baseline headers

All credential-bearing GitHub REST adapters use the shared `tools/github_http_security.py::github_api_headers()` helper for the mandatory API media type and explicit GitHub API version. Adapter-specific headers such as `Authorization` and `Content-Type` remain local to the request boundary.

The helper is the single source of truth for the API version. Individual providers must not duplicate the version constant or construct a parallel baseline header map.
## GitHub REST response bounds

Credential-bearing GitHub REST adapters read response bodies through the shared bounded transport primitive. Successful and HTTP-error bodies are capped before decoding, preventing unexpectedly large JSON responses from becoming unbounded in-memory data. The limit is one mebibyte; responses exceeding it fail closed.

After the byte bound is enforced, every credential-bearing GitHub REST adapter parses the response through `github_http_security.parse_github_json()`. The parser rejects duplicate object keys, non-standard JSON constants, invalid UTF-8, and malformed JSON before provider data is interpreted. It accepts any valid JSON root because GitHub endpoints may legitimately return objects, arrays, or empty bodies; endpoint-specific code remains responsible for validating the expected response shape.
