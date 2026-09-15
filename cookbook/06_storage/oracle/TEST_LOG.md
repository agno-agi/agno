### oracle_for_agent.py

**Status:** PARTIAL

**Description:** Agent storage on Oracle, with conversation history surviving
a restart. The storage layer this example exercises (session and run
persistence, retrieval, cascade delete) was verified directly and
exhaustively against a live Oracle server — see
`.scratch/oracle-integration/scripts/validate_ticket03.py` and the
differential harness at
`libs/agno/tests/integration/db/test_differential_oracle_postgres.py`, both
green against Oracle 18c, 21c and 23ai+.

**Result:** Re-run for this ticket, in `.venvs/demo` against a live server
(port substituted for the dedicated test container, since port 1521 was
occupied by an unrelated container in this environment): `OracleDb`
construction, table creation, and both `Agent(db=db, ...)`/
`agent.print_response(...)` calls all run and correctly persist to Oracle —
confirmed by inspecting the tables directly. Both calls fail only at the
actual model call (`OPENAI_API_KEY not set`), which is expected — no LLM API
key was available in this environment. Re-run with a real API key to confirm
the print_response calls end to end before relying on this entry as a full
pass.

**Caveat, not a defect in this example:** if the default `agno_sessions`/
`agno_runs` tables already exist from an earlier, separate process (an app
restart, or a second script pointed at the same database), a real,
previously-undiscovered bug in `OracleDb`/`AsyncOracleDb` surfaces on the
next run's upsert — recorded as a finding against ticket 03
(`.scratch/oracle-integration/issues/03-agent-conversation-on-oracle.md`),
not fixed here. Dropping and recreating the tables (or pointing at a fresh
database) avoids it; this is exactly what a first-time run of this example
does.

---

### oracle_for_team.py

**Status:** PARTIAL

**Description:** Team storage on Oracle, two agents collaborating through a
`HackerNewsTools`/`WebSearchTools`-driven research task.

**Result:** Verified in `.venvs/demo` against a live server: `OracleDb`
construction and `Team(db=db, ...)` construction succeed;
`hn_team.print_response(...)` runs and fails only at the model call
(`OPENAI_API_KEY not set`), with no database error. Re-run with a real API
key to confirm the full research-and-summarize flow.

---

### oracle_for_workflow.py

**Status:** PARTIAL

**Description:** Workflow storage on Oracle, a two-step content-creation
pipeline (a research team, then a content-planning agent).

**Result:** Verified in `.venvs/demo` against a live server: `Workflow(db=
OracleDb(...), ...)` construction succeeds and `print_response(...)` runs
both steps, each failing only at its own model call (`OPENAI_API_KEY not
set`), with no database error. Re-run with a real API key to confirm the
full pipeline.

---

### shared_engine.py

**Status:** PASS

**Description:** Configures an Oracle engine via `create_oracle_engine` and
shares it with `OracleDb` and `DbFileSystem`. The entrypoint only inspects
engine identity — no query is issued.

**Result:** Ran in `.venvs/demo`; printed engine-configured confirmation and
`True` for shared-engine identity, exactly as expected. No live connection is
opened by this example.

---

See [`async_oracle/TEST_LOG.md`](async_oracle/TEST_LOG.md) for the
asynchronous examples.
