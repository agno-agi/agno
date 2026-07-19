# Test Log: reliability

Last run: 2026-07-19, with live `OPENAI_API_KEY`. `ReliabilityEval` matches tool
executions: expectations are satisfied only by clean tool executions.

### db_logging.py

**Status:** FAIL (environmental)

**Description:** Runs reliability evaluation and stores results in PostgreSQL.

**Result:** The evaluation itself reports PASSED under execution matching, but the db
logging step cannot connect: the file hardcodes `localhost:5432` while the repo's
`run_pgvector.sh` container maps `5532:5432`. Pre-existing port mismatch in this
cookbook's db_url; the eval logic itself passes.

---

### reliability_async.py

**Status:** PASS

**Description:** Runs reliability evaluation using `arun`.

**Result:** `factorial` matched as a clean execution; eval PASSED.

---

### single_tool_calls/calculator.py

**Status:** PASS

**Description:** Validates a single expected factorial tool call, including argument
validation.

**Result:** Both functions passed: expected tool matched as a clean execution and the
argument check matched against `ToolExecution.tool_args`.

---

### multiple_tool_calls/calculator.py

**Status:** PASS

**Description:** Validates expected multiply and exponentiate tool calls.

**Result:** PASSED; extra call correctly classified as additional under
`allow_additional_tool_calls=True`.

---

### team/ai_news.py

**Status:** PASS

**Description:** Validates team delegation and news-search tool calls.

**Result:** PASSED. Exercises the member-execution union: `delegate_task_to_member`
matched from the leader's executions and `search_news` from
`member_responses[0].tools`.

---

### 01_demo/evals (cross-reference)

`cookbook/01_demo/evals` reliability cases run through the suite; spot-checked
`local_wiki_reports_state_honestly` live on 2026-07-19: Judge PASS, Reliability PASS,
exit 0 under execution matching.
