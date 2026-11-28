# Prime integration parity

- [x] Keyword-only configuration and read-only SDK identity.
- [x] Shared sync/async run, printing, AgentOS, retries, background and session APIs.
- [x] Preserve tool executions in non-streaming and streaming runs.
- [x] Translate reported usage, cost and actual model/provider into run and session metrics.
- [x] Interrupt live CLI runs through shared cancellation hooks.
- [x] Native image/text attachments using shared staging and cleanup.
- [x] Native skill flags and ephemeral sessions.
- [x] Sync/async manual compaction with idle-session guards.
- [x] Focused cookbook examples and regression tests authored.
- [x] Async, background, cancellation, local skills, ephemeral-history, adapter-recovery and HTTP-session cookbooks authored.
- [x] Run formatting and static validation; baseline failures are recorded in TEST_LOG.md.
- [ ] Run unit tests and live CLI examples after user authorization.

Prime owns its native session files and internal tools/subagents. Unsupported
Claude/Codex configuration, native session-store hooks and checkpoint APIs are omitted.
