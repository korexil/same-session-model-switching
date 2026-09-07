# Changelog

## 0.1.0 - 2026-09-08

First versioned evidence snapshot.

- Added the executable controller, atomic desired-state store, context planner,
  and failure/degraded-state semantics.
- Added in-memory and loopback HTTP A → B → A rehearsals with exact-session,
  revision, correlation, rollback, and stale-evidence checks.
- Added the opt-in live-minimal harness, isolated Claude Code `Read` tool proof,
  exact model/version checks, and a secret-free receipt bound to the harness
  SHA-256.
- Added architecture, implementation, security, provider, subscription,
  context-recovery, support, and contribution guidance.
