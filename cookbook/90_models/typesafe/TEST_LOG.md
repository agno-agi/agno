# TEST_LOG

### self_hosted.py

**Status:** PASS (local mock)

**Description:** `DecisionModel` against a local mock of the System One API at `http://localhost:30000/v1/systemone`, asking one `Noul` question.

**Result:** Printed the mocked probability. Exercises the real HTTP path; not yet run against an SGLang server.

---

### basic.py

**Status:** NOT RUN

**Description:** Three question types against Jev.

**Result:** Needs `TYPESAFE_API_KEY`; the request and response handling is covered by unit tests with a mocked transport.

---

### async_basic.py

**Status:** NOT RUN

**Description:** Concurrent `adecide` calls against Jev.

**Result:** Needs `TYPESAFE_API_KEY`.

---

### agent_triage.py

**Status:** PASS (local mock)

**Description:** `Agent(model=Jev(), output_schema=Ticket)` with `Choice`, `Noul` and `Score` fields, sync and async, against a local mock of the System One API.

**Result:** Returned a filled `Ticket` and per-field answers in `run.decisions`. Not yet run against the live Jev API.

---

### agent_with_guardrail.py

**Status:** PASS (local mock)

**Description:** Decision agent with a pre-hook guardrail and SQLite storage, three posts in one session, against a local mock.

**Result:** Two posts completed, the empty post was blocked by the guardrail with status ERROR, and all three runs were stored in the session.

---
