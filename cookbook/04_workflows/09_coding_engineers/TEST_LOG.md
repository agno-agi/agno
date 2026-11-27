# TEST_LOG for cookbook/04_workflows/09_coding_engineers

Tested 2026-11-27 on macOS with Docker, image `agno-sandbox:local`, PostgreSQL in the `pgvector` container, against https://github.com/agno-agi/agno/pull/11950 (2 files, +36 -1). Nothing was pushed or posted: the sandboxes held no GitHub token.

### pr_to_merge_ready.py

**Status:** PASS with Codex in every engineer seat. NOT YET RUN with a Claude engineer: the Anthropic key available to the test was refused ("Invalid API key").

**Description:** The whole workflow, end to end, twice. Because of the refused key, the two `ClaudeAgent` seats (Claude reviewer, fixing engineer) were filled by `CodexAgent` on `gpt-5.6-luna` for these runs; the workflow itself was unchanged. Triage ran on `gpt-5.6-luna`.

**Result:**

- Both runs completed all three rounds: 323 s and 389 s. Each round ran the two reviews at the same time in two containers, then triage, then the fix in a third container. From round two on, both reviewers applied the fixing engineer's printed diff with `git apply` and reviewed the result.
- Neither run ended merge-ready. Triage on `gpt-5.6-luna` kept one or more points in every round, and in the second run it kept a point about code the pull request does not touch, so the fix grew past the pull request. A stronger triage model is the first thing to try (`TRIAGE_MODEL`).
- Token use in the second run, all three rounds: reviewers 4.6 million input tokens (4.4 million read from cache) and 23 thousand output; fixing engineer 1.4 million input (1.3 million from cache) and 11 thousand output; triage 11 thousand input and 3 thousand output.
- The engineers could not run the tests: the stock sandbox image has no `pytest`.
- Run as a background run from Super Agent on AgentOS (`AgentOS(workflows=[workflow])`, durable queue): started with `start_background_run`, completed in about 150 s, and Super Agent reported the result.

---
