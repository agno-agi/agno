# TEST_LOG for cookbook/04_workflows/09_coding_engineers

Tested 2026-11-27 on macOS with Docker, image `agno-sandbox:local`, PostgreSQL in the `pgvector` container, against https://github.com/agno-agi/agno/pull/11950 (2 files, +36 -1, already merged). Nothing was pushed or posted: the sandboxes held no GitHub token.

### pr_to_merge_ready.py

**Status:** PASS

**Description:** The whole workflow, end to end, with the Claude reviewer and the fixing engineer on `claude-sonnet-5-5` and the Codex reviewer on `gpt-5.6-luna`, each in its own Docker sandbox. Run twice: once with triage on the default `gpt-5.6-luna`, once with `TRIAGE_MODEL=gpt-6.1-terra`.

**Result:**

- Triage on `gpt-6.1-terra`: merge-ready after one round, in 68 s. Triage dropped both points the Codex reviewer raised, as problems that were there before the pull request. No fix was made. Claude cost $0.02.
- Triage on `gpt-5.6-luna` (the default): all three rounds ran, in 217 s, and the result was "Not confirmed merge-ready". Triage kept two or three points in every round, about identity checks and trust in wiki pages that a change to a prompt cannot settle, so each fix led to new points. Claude cost $0.28 for the three rounds: $0.14, $0.08 and $0.06. The Codex reviewer used 216 to 324 thousand input tokens a round, most of them read from cache; Agno records no cost for it.
- So triage decides whether the rounds end. Set `TRIAGE_MODEL` to the strongest model you have.
- In every round the two reviews ran at the same time in two containers. From round two on, both reviewers applied the fixing engineer's printed diff with `git apply` and reviewed the result.
- The engineers could not run the tests: the stock sandbox image has no `pytest`.
- Run as a background run from Super Agent on AgentOS (`AgentOS(workflows=[workflow])`, durable queue, Codex in every engineer seat): started with `start_background_run`, completed in about 150 s, merge-ready after two rounds, and Super Agent reported the result.
- A run from this script leaves its sandbox containers paused when the process exits. Remove them with `docker ps -aq --filter label=io.agno.sandbox.agent=merge-ready-fixer | xargs docker rm -f`, and the same for `merge-ready-claude-reviewer` and `merge-ready-codex-reviewer`.

---
