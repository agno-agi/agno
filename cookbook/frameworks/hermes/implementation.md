# Hermes integration

- [x] Keyword-only adapter with lazy native import and `sdk="hermes"`.
- [x] Inherit sync/async run, printing, AgentOS, storage and retry APIs.
- [x] Move blocking native execution to a dedicated worker thread.
- [x] Translate text/tool callbacks and reconcile current-turn transcript tools.
- [x] Store native messages per user/session, with database-backed history replay.
- [x] Report native model/provider and per-turn usage/cost.
- [x] Connect cancellation and stream cleanup to native interruption.
- [x] Author basic, native SDK, tools, sessions and AgentOS examples.
- [x] Author focused regression tests.
- [x] Run formatting and static validation; baseline failures are recorded in TEST_LOG.md.
- [ ] Execute unit tests after user authorization.
- [ ] Verify examples in an activated, authenticated Hermes environment.

Uploads, provider-enforced structured output, native compaction and checkpoint
continuation are outside this adapter's current surface.
