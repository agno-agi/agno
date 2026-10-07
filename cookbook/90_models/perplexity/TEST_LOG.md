# TEST_LOG

### decisions.py

**Status:** NOT RUN

**Description:** Ticket triage on Perplexity's Decisions API with `PerplexityDecisions`.

**Result:** Needs `PERPLEXITY_API_KEY`; the request and response handling is shared with `Jev` and covered by unit tests with a mocked transport. The existing chat cookbooks in this folder were not re-run.

---

### decisions_agent.py

**Status:** PASS (local mock)

**Description:** Triage agent on `PerplexityDecisions`, against a local mock of the System One API.

**Result:** Returned a filled `Ticket` and per-field answers. Not yet run against the live Perplexity API.

---
