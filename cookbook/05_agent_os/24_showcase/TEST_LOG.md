# Test Log: 24_showcase

Tested on 2026-07-24 against Agno source commit
`45bfff9f2aa6ec11b7386c3cd3bf6d1141d005dc`, and `demo.py` re-tested on
2026-08-24 after its eval persistence check moved from
`accuracy_evaluation.eval_id` to `result.run_id`.

The lesson was loaded from the rewrite worktree and exercised with the demo
Python environment, PostgreSQL with pgvector on port 5532, `gpt-5.5`, and
`claude-sonnet-4-6`.

### _agents.py

**Status:** PASS

**Test mode:** LIVE (support module — no `__main__`; its objects were imported
and driven by a test harness)

**Description:** Loaded the current AgentOS introduction into the
`Agno Documentation` knowledge base, searched pgvector, then ran Agno Assist
and Sage with their configured models and tools.

**Result:** The knowledge search returned 2 document chunks. Agno Assist run
`9ba0f654-3d9e-439a-8401-4d6534b46edf` called
`search_knowledge_base`, identified Agents, Teams, and Workflows, and cited
`https://docs.agno.com/agent-os/introduction.md`. Sage run
`db9591cc-3f19-4531-89c8-48c1114c6e06` called
`get_current_stock_price` and `search_news`, then returned dated NVIDIA market
data with a linked news source.

---

### _teams.py

**Status:** PASS

**Test mode:** LIVE (support module — no `__main__`; its objects were imported
and driven by a test harness)

**Description:** Ran the Finance Team in broadcast mode with a current NVDA
and AMD comparison that required both registered members and live financial
data.

**Result:** Team run `a4f62211-5d17-43ee-911f-817eb60be176`
completed with member responses from Sage and Market Analyst. Both members
retrieved the two current prices, and the `gpt-5.5` Team leader reconciled
their results into a sourced table with timing caveats.

---

### demo.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Re-tested 2026-08-24 on `SHOWCASE_PORT=17879` after the eval
persistence check moved to `result.run_id`: prepared knowledge, ran the real
accuracy evaluation, and exercised authentication and the eval endpoints.

**Result:** AccuracyEval `da6e8c87-0250-40d3-aec3-2c8398810a51` scored `10/10`
with the `claude-sonnet-4-6` judge, and the persistence assertion read its row
back by `result.run_id`. Anonymous `GET /config` returned `401`, authenticated
`200`, and the eval list returned three stored runs, each under its own id. The
server shut down cleanly with no remaining listener. The 2026-07-24 pass on
`17877` covered more surface: AccuracyEval
`0a7df9c3-aecc-4ee5-bc2e-fa7165bb234a` at `10/10`, persistence via eval
`47325c0e-73c5-4477-87e7-38dc4f5323ce`, discovery returning exactly
`agno-assist`, `sage`, and `finance-team`, Agent run
`46f18a31-9a8e-4db5-810b-c63e14275ec0` after a knowledge search, and trace
`f43d8d4a65e4c0218fc6f84ef9df77a2` with 4 spans.

---

## Validation

- Recursive pattern validation checked exactly 3 Python files with 0
  violations.
- Targeted Ruff format and check, Python compilation, inventory parity, local
  Markdown links, legacy deletion, and `git diff --check` passed.
- PostgreSQL and pgvector remained running for the shared cookbook test
  environment; no showcase server process or listener remained.
