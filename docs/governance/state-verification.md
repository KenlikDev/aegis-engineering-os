# State Verification and Evidence Provenance

Aegis must distinguish user intent from externally verifiable state.

The product owner is authoritative about intent, preferences, delegated authority, and business decisions. Aegis must independently verify technical and external facts whenever the state can be observed.

## State categories

### Intent

Examples:

- "Use squash only."
- "The rule has been changed."
- "I want Jira to be the task tracker."

These statements define requested intent or a desired configuration.

### Claim about external state

Examples:

- "ai/integration now requires CI."
- "The build is green."
- "Jira is connected."
- "This dependency is already installed."

These claims must be verified before Aegis relies on them as facts.

### Observed fact

A current observation from GitHub, the repository, CI, a build, an integration API, or another authoritative source.

Only observed facts should be used as proof of current state.

## Verification record

For material state, record:

- source;
- subject or object identifier;
- commit or revision when available;
- observation time with an explicit timezone;
- relevant result;
- unresolved uncertainty;
- reference links when useful;
- an integrity hash when an evidence artifact is persisted.

The canonical executable envelope is defined by `tools/evidence_contract.py` and recorded through `tools/state_verification.py`. Its SHA-256 identity covers the normalized evidence payload while excluding only the identity fields themselves.

## Installed Aegis project state

Project verification is an independent trust boundary. `tools/verify_project.py` rejects ambiguous state JSON, symbolic links for the `.aegis` state root or file, and symbolic links in the managed `.agents/skills` root, skill directories, and managed `SKILL.md` files before calculating integrity checksums.

The verifier does not assume bootstrap created the state safely. It validates the filesystem topology first and then validates the strict state schema and recorded checksums.

## Secure installed-project reads

`tools/verify_project.py` treats filesystem topology checks as a TOCTOU-sensitive boundary. Managed state, skill files, and managed `AGENTS.md` are read through anchored directory file descriptors with `O_NOFOLLOW`, and the final object is verified as a regular file from the opened descriptor.

The earlier `is_symlink()` checks remain useful for deterministic diagnostics but are not the security primitive by themselves. A concurrent path substitution cannot redirect the verified read through a symlinked file or ancestor directory.



## Mutation verification

A successful write response is not sufficient proof that the intended state now exists when the system supports read-after-write verification.

After a material mutation, Aegis should read the resulting object back and verify the expected state.

## Freshness rule

When a user reports a change, Aegis should perform a fresh verification rather than merely echoing the claim.

When Aegis itself performs a change, it should verify the result from the authoritative system.

## Conflict handling

If local state, remote state, documentation, CI, or user statements disagree, Aegis should stop relying on the disputed fact until the discrepancy is explained or explicitly recorded as uncertainty.


## Secure verifier descriptor ownership

Secure verifier reads use anchored directory file descriptors and `O_NOFOLLOW`. The directory descriptor is closed exactly once, while a returned regular-file descriptor remains owned by the caller. Validation failures preserve their original error instead of being replaced by descriptor cleanup failures.
