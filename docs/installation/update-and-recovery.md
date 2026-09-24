# Aegis Update and Recovery

## Normal update

1. Fetch the Aegis repository.
2. Detect a newer candidate version.
3. Validate repository structure and skills.
4. Review the candidate against the active known-good version.
5. Run skill scenarios and representative tasks.
6. Promote only after acceptance criteria pass.
7. Keep the previous known-good version available for rollback.

## Offline recovery

If GitHub or the internet is unavailable:
- continue from the local known-good clone;
- do not fabricate current external facts;
- mark external verification as pending.

## Failed update

A failed candidate remains isolated. The active version is unchanged.

## Restoring from corruption

Keep a local Git mirror and use a known commit or tag as the recovery point. Reinstall project-local skills from the recovered known-good version.
