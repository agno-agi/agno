### async_oracle_for_agent.py

**Status:** PARTIAL

**Description:** Agent storage on `AsyncOracleDb`, with conversation history
surviving a restart. The async adapter's storage layer this example
exercises was verified directly and exhaustively against a live Oracle
server — see `.scratch/oracle-integration/scripts/validate_ticket13.py`,
`validate_ticket14.py`, and the async differential harness at
`libs/agno/tests/integration/db/test_differential_async_oracle_postgres.py`,
all green against Oracle 18c, 21c and 23ai+.

**Result:** Verified in `.venvs/demo` against a live server: `AsyncOracleDb`
construction and both `await agent.aprint_response(...)` calls run and
correctly persist to Oracle, failing only at the model call
(`OPENAI_API_KEY not set`), with no database error, when run against tables
created fresh by this same run. Re-run with a real API key to confirm the
print_response calls end to end.

**Same caveat as the synchronous example, confirmed live for the async
adapter too:** if `agno_sessions`/`agno_runs` already exist from an earlier
process, the reflection bug recorded against ticket 03 surfaces here as well
— `async_oracle.py`'s own `_reflect_table` has the identical gap. Not fixed
here, per this ticket's own instruction.

---

### async_oracle_for_team.py

**Status:** PARTIAL

**Description:** Team storage on `AsyncOracleDb`.

**Result:** Verified in `.venvs/demo` against a live server, against freshly
created tables: `AsyncOracleDb` and `Team(db=db, ...)` construction succeed;
`asyncio.run(hn_team.aprint_response(...))` runs and fails only at the model
call, with no database error. Re-run with a real API key to confirm the full
flow.

---

### async_oracle_for_workflow.py

**Status:** PARTIAL

**Description:** Workflow storage on `AsyncOracleDb`, the same two-step
content-creation pipeline as the synchronous example.

**Result:** Verified in `.venvs/demo` against a live server, against freshly
created tables: construction succeeds and both workflow steps run, each
failing only at its own model call, with no database error. Re-run with a
real API key to confirm the full pipeline.
