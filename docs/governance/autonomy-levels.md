# Autonomy Levels

Aegis autonomy is configurable. Higher autonomy expands what the agent may execute without human approval; it does not remove quality gates.

## Level 0 — Advisory

The AI analyzes and recommends. No repository changes.

## Level 1 — Local Implementation

The AI may modify local branches and run verification.

## Level 2 — Autonomous Task Branch

The AI may create ai/* branches, commit, test, and prepare changes.

## Level 3 — Autonomous GitHub Staging

The AI may push verified task branches and integrate into ai/integration according to repository policy.

## Level 4 — Autonomous PR Maintenance

The AI may create and update pull requests and remediate CI failures.

## Level 5 — Autonomous Development Maintenance

The AI may perform approved maintenance work across the project without per-change approval.

Production deployment remains separately governed even at high autonomy levels.
