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

**Result:** Every step short of the actual model call was verified against
`.venvs/demo`: `OracleDb` construction against a live Oracle server, and
`Agent(db=db, model=OpenAIResponses(...), add_history_to_context=True)`
construction with that db, both succeed. The example was not run end to end
with a real model call in this environment — no LLM API key was available.
Re-run with a real API key to confirm the print_response calls end to end
before relying on this entry as a full pass.

---
