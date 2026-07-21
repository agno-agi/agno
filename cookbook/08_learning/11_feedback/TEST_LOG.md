# Test Log

### 01_basic_feedback.py

**Status:** PASS

**Description:** Agent with feedback learning enabled. First run answers a factual question verbosely. Thumbs down feedback with a comment ("Too verbose. Just give me the number") is recorded on the run; the model distills a lesson from it. A second run in a new session picks the feedback up from the injected context.

**Result:** Feedback recorded and lesson distilled ("For direct factual questions, answer with the simplest likely number first and avoid extra context unless asked."). The second run answered with just the number, confirming the agent adapted to the feedback.

---

### 02_conversational_feedback.py

**Status:** PASS

**Description:** No-UI feedback flow. The user complains in the conversation ("Too long. Next time just give me the number, nothing else."). After the run, the feedback store's extraction pass detects it, records signal thumbs_down with the user's words as the comment and a distilled lesson, and a brand new session answers concisely.

**Result:** Extraction recorded "[thumbs_down] Too long. Next time just give me the number, nothing else." with lesson "Keep answers concise and provide only the requested number when asked." The new session's answer was reduced to the numbers, confirming adaptation without any endpoint or UI involvement.

---
