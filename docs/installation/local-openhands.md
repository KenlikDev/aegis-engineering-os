# Local Aegis Installation for OpenHands

## Goal

Keep Aegis in a local Git clone, pin a known-good version, and install selected skills into each target project under .agents/skills/.

OpenHands recognizes project-local AGENTS.md and skills under .agents/skills/ when they are present in the project workspace.

## Local clone

Clone this repository somewhere stable on the development VM, for example:

    ~/aegis-engineering-os

Do not place the only copy on a removable or disposable workspace.

## Bootstrap a project

From the Aegis repository:

    python3 tools/bootstrap_project.py /path/to/project --preset core

For product-discovery work:

    python3 tools/bootstrap_project.py /path/to/project --preset all

Use --dry-run before changing an unfamiliar project.

## Pinning and verification

After each deliberate Aegis update, the target project's .aegis/aegis-version.json records:

- the exact Aegis version and source commit;
- the fact that the source worktree was clean;
- the selected preset and effective integrations;
- the exact installed skill set;
- a SHA-256 checksum for every installed skill.

Bootstrap refuses to run from a dirty Aegis source clone.

Changing presets during a later bootstrap removes only skills previously recorded
as managed by Aegis, refuses to overwrite unowned project skills, and refuses to
overwrite or delete customized managed skill directories. Project-local skills
not recorded in Aegis state are left untouched.

Bootstrap stages changes before applying them and rolls back managed skills and
state when a mutation fails.

Verify an installed project after recovery or when integrity is uncertain:

    python3 tools/verify_project.py /path/to/project

The verifier does not need network access or the Aegis source clone because it validates the installed files against the recorded checksums.

Do not replace the active Aegis knowledge during a running session.

## Offline operation

The local clone is the operational fallback. If GitHub or the internet becomes unavailable, continue using the last active known-good version.

External facts that cannot be verified offline must be marked pending and rechecked after connectivity returns.

## Update discipline

1. Fetch the Aegis repository when online.
2. Validate the candidate version.
3. Review changes.
4. Promote the candidate only after validation.
5. Pin new sessions to the promoted version.
6. Verify each bootstrapped project after recovery or an integrity-sensitive update.

Never replace the only known-good local copy with an unvalidated update.
