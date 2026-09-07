# Support and evidence matrix

This project separates executable reference support from dated live evidence.
"Listed" never means that a provider is currently available to every account.

## Reproduction paths

| Path | Session owner | Real provider traffic | Transcript/workspace continuity | Tool evidence | Transaction/race semantics | Evidence level |
| --- | --- | --- | --- | --- | --- | --- |
| `reference/demo.py` | In-memory reference shell | No | Deterministic assertion | Simulated | Full controller unit suite | Credential-free rehearsal |
| `reference/http_demo.py` | Reference shell + loopback bridge | No | Deterministic assertion across JSON/HTTP | Simulated | Revision/correlation evidence over HTTP | Networked rehearsal |
| `examples/live-minimal/live_minimal.py` | One Python process | Yes, opt-in | Random markers cross A → B → A; temporary workspace survives B | Official Claude Code `Read` recovers an unknown file marker | Not exercised by this harness | `continuity-verified` + `tool-verified` for the dated snapshot |

The live harness complements the controller; it does not replace it. The
controller tests prove ordering, stale-evidence rejection, rollback, degraded
state, and last-writer-wins behavior. The live harness proves that two real
adapter paths can carry one outer transcript and workspace evidence. A
production claim needs both.

## Verified live snapshot

The committed [2026-09-07 receipt](examples/live-minimal/verified-2026-09-07.json)
is bound to the exact harness file by SHA-256.

| Component | Verified value | What was checked |
| --- | --- | --- |
| Route A transport | CLIProxyAPI 7.2.128 (`bd34ceca`) | Two successful Messages-compatible requests |
| Route A model | `gpt-5.6-sol` | Requested model equals response `model` on A1 and A2 |
| Route B transport | Official Claude Code CLI 2.1.259 | Safe/restricted print mode; settings, plugins, hooks, MCP, and persistence disabled |
| Route B model | `claude-haiku-4-5-20251001` | Expected model appears in CLI `modelUsage`; no fallback accepted |
| Tool | Built-in Claude Code `Read` | Random file marker absent from the prompt appears in B's result |
| Continuity | A → B → A | Transcript marker reaches B; transcript and workspace markers return to A |
| Privacy | Synthetic inputs only | Receipt excludes endpoint, credential, prompt, response, marker, raw IDs, paths, and exact time |

This snapshot is evidence for those exact versions and models on that date. A
new gateway build, CLI version, route mapping, or model requires a fresh live
run and receipt. Model discovery alone is not a refresh.

## Explicitly not verified

- provider-private reasoning or hidden cache migration;
- portability of provider-owned server threads;
- streaming and incremental tool-argument normalization on the live paths;
- images or other multimodal inputs;
- realistic long-context behavior;
- live busy-session queueing and rollback;
- universal subscription, OAuth, quota, price, or regional availability.

Until a row has a version-bound positive test, describe it as `documented` or
`unverified`, not supported.

## Compatibility and release policy

- Hosted CI currently runs Python 3.12 with no third-party runtime dependency.
- The provider adapter contract is pre-1.0 and may change between minor
  releases. A schema-breaking change must be called out in the release notes.
- Git tags freeze repository evidence, not provider availability. Re-run the
  live harness after upgrading either external runtime.
- Security reports belong in GitHub private vulnerability reporting; usage and
  integration questions belong in ordinary issues after removing secrets and
  private infrastructure details.
