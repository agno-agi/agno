# Advisor Tools - Test Log

## 2026-08-05

### 01_basic.py

**Status:** PASS

**Description:** Single Gemini advisor attached to a gpt-5.5 agent. Agent drafts a DNS explanation, calls ask_advisor for a second opinion, and incorporates the feedback.

**Result:** Agent called ask_advisor, received Gemini feedback, and produced an improved final answer.

---

### 02_multi_advisor.py

**Status:** PASS

**Description:** Claude and Gemini advisors with descriptions. Agent uses ask_all_advisors to poll both on a microservices vs monolith question.

**Result:** Agent called ask_all_advisors with a draft as context; both advisors responded and their feedback was incorporated. No advisor errors.

---

### 03_escalation.py

**Status:** PASS

**Description:** Small primary model (gpt-5-mini) with large advisors defined as model strings ("anthropic:claude-sonnet-4-6", "openai:gpt-5.5"). Descriptions steer code questions to Claude.

**Result:** Model strings resolved correctly. Agent escalated the interval-merging implementation to the Claude advisor via ask_advisor(advisor="claude-sonnet-4-6") and applied the review feedback.

---

### 04_custom_system_message.py

**Status:** PASS

**Description:** Custom system_message turns a Gemini advisor into a medical content reviewer. Agent drafts a health answer and sends it for domain-specific review.

**Result:** Advisor reviewed the draft against the custom criteria; agent applied fixes and kept the healthcare disclaimer.

---

### 05_async.py

**Status:** PASS

**Description:** Async run (aprint_response) with Claude and Gemini advisors. ask_all_advisors queries both advisors in parallel via asyncio.gather.

**Result:** Async tool variant invoked; both advisors responded in parallel. No errors.

---
