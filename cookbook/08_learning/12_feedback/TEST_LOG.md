# Test Log: 12_feedback

Runs below observed against Postgres + gpt-5.5. Each cookbook uses its own
session ids so they don't share history. Feedback is agent-scoped and persists
across runs, so re-running an example on a dirty database accumulates prior
feedback (the same behavior as the other stores).

### 01_basic_feedback.py

**Status:** PASS

**Description:** Explicit run review. Test 1 answers verbosely; Test 2 records a negative signal via `feedback_store.record()` and distills a lesson; Test 3 (new session) answers concisely.

**Result:** Test 1 returned a multi-line answer (Tokyo Metropolis ~14 million, Greater Tokyo ~37 million, plus the 23-special-wards note). Recorded a negative signal with distilled lesson "When asked for a simple fact, answer directly with just the requested number unless clarification is necessary." Test 3 answered "About **2.8 million**." - concise, confirming the agent adapted.

---

### 02_conversational_feedback.py

**Status:** PASS

**Description:** No-UI feedback. The user complains in the conversation ("Too long. Next time just give me the number, nothing else."). After the run, ALWAYS-mode extraction records the complaint automatically (with the prior response captured as context); a new session answers concisely.

**Result:** Test 1 returned a verbose answer (Metropolis / Greater Tokyo breakdown). Extraction recorded "[negative] Too long. Next time just give me the number, nothing else." with lesson "Provide only the requested number without extra explanation when the user asks for a simple fact." The second turn of the same session already answered "14 million". Test 3 (new session) answered "About 2.8 million." Verified reproducible even when run immediately after 03 - the distinct session ids prevent cross-cookbook history pollution.

---

### 03_agentic_feedback.py

**Status:** PASS

**Description:** AGENTIC mode. The agent is given a record_feedback tool. When the user reacts ("Too long. Next time just give me the number"), the agent calls record_feedback itself during the run (providing the context of what was reviewed), rather than a background extraction pass. Test 3 (new session) confirms the agent adapted.

**Result:** The agent invoked `record_feedback(signal=negative, comment="Too long. Next time just give me the number, nothing else.", learning="For direct factual questions, answer with just the requested number when the user asks for brevity.", context="The assistant gave multiple Tokyo population figures and explanatory text.")` as a tool call in the same turn. The context describes the response actually in the agent's window - AGENTIC turns chat history on, so the agent reviews the turn the feedback refers to rather than a response it never saw. Test 3 answered "Osaka city has about 2.8 million people. / Osaka Prefecture has about 8.8 million people." - two short lines rather than the original multi-paragraph shape; the agentic path records and adapts end to end, though the adaptation is less pronounced than the ALWAYS-mode runs.

---
