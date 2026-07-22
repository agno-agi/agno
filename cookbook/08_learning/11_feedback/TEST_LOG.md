# Test Log: 11_feedback

Runs below observed on a clean database, verified against pgvector + gpt-5.5.
Each cookbook uses its own session ids so they don't share history. Feedback is
agent-scoped and persists across runs, so re-running an example on a dirty
database accumulates prior feedback (the same behavior as the other stores).

### 01_basic_feedback.py

**Status:** PASS

**Description:** Explicit run review. Test 1 answers verbosely; Test 2 records a negative signal via `feedback_store.record()` and distills a lesson; Test 3 (new session) answers concisely.

**Result:** Test 1 returned a multi-line answer (Tokyo Metropolis ~14 million, Greater Tokyo ~37-38 million). Recorded a negative signal with distilled lesson "When asked for a simple factual value, provide only the direct answer unless clarification or context is requested." Test 3 answered "About 2.8 million people." - concise, confirming the agent adapted.

---

### 02_conversational_feedback.py

**Status:** PASS

**Description:** No-UI feedback. The user complains in the conversation ("Too long. Next time just give me the number, nothing else."). After the run, ALWAYS-mode extraction records the complaint automatically (with the prior response captured as context); a new session answers concisely.

**Result:** Test 1 returned a verbose answer (Metropolis / Greater Tokyo breakdown). Extraction recorded "[negative] Too long. Next time just give me the number, nothing else." with lesson "Provide only the number when asked for population, without extra explanation." Test 3 (new session) answered concisely. Verified reproducible even when run immediately after 03 - the distinct session ids prevent cross-cookbook history pollution.

---

### 03_agentic_feedback.py

**Status:** PASS

**Description:** AGENTIC mode. The agent is given a record_feedback tool. When the user reacts ("Too long. Next time just give me the number"), the agent calls record_feedback itself during the run (providing the context of what was reviewed), rather than a background extraction pass. Test 3 (new session) confirms the agent adapted.

**Result:** The agent invoked `record_feedback(signal=negative, comment="Too long...", learning="For similar future requests, respond with only the requested number and no extra text.")` as a tool call in the same turn, and the feedback was stored. Test 3 answered "Osaka city has a population of about 2.8 million people." - concise, confirming the agent-driven path adapts end to end.

---
