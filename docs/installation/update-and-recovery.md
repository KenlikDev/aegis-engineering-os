# Aegis Update and Recovery

## Normal update

1. Fetch the Aegis repository.
2. Detect a newer candidate version.
3. Validate repository structure and skills.
4. Review the candidate against the active known-good version.
5. Run skill scenarios and representative tasks.
6. Promote only after acceptance criteria pass.
7. Keep the previous known-good version available for rollback.

## Bootstrap state

Each bootstrapped project records its effective Aegis installation in
.aegis/aegis-version.json:

- schema_version;
- Aegis version and source commit;
- source repository;
- source worktree cleanliness;
- selected preset;
- effective optional integrations;
- sorted installed skill names;
- SHA-256 checksums for every installed skill;
- active status.

The bootstrap state is deterministic for identical inputs. Re-running bootstrap
with a different preset reconciles skills previously installed by Aegis while
leaving unrelated project-local skills untouched. Aegis refuses to overwrite
unowned skills or customized managed skills.

Bootstrap stages the selected skills before mutating the target project and
uses rollback protection for managed files and state. The state file itself is
written atomically.

The tools/verify_project.py utility verifies that the recorded installed skills
still exist and match their recorded checksums.

## Source provenance

Bootstrap refuses to run from a dirty Aegis source worktree. The recorded
source commit therefore identifies the clean source revision used to build the
installed skill set.

## Offline recovery

If GitHub or the internet is unavailable:
- continue from the local known-good clone;
- do not fabricate current external facts;
- mark external verification as pending.

## Failed update

A failed candidate remains isolated. The active version is unchanged.

## Restoring from corruption

Keep a local Git mirror and use a known commit or tag as the recovery point.
Reinstall project-local skills from the recovered known-good version, then run
tools/verify_project.py against the target project.
