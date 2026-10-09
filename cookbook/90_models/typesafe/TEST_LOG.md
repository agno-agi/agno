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
