# Test Log - _12_audio_extraction

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Downloads `sample_conversation.wav` and extracts a generic `CallSummary` (caller_intent, key_topics, next_action) via `output_schema` on a Gemini agent.

**Result:** Returned `CallSummary(caller_intent='Discuss taking on a new project lead role', key_topics=['project lead role', 'career transition'], next_action='The caller will update Liam on their decision or progress with the role')`. 1092 input / 43 output tokens, 4.8s.

---

### call_summary.py

**Status:** PASS

**Description:** Extracts a support-desk-shaped `SupportCall` (issue, resolution_status, customer_sentiment, follow_up_required, notes) with Literal-constrained fields from the same conversation clip.

**Result:** Returned `issue='Discussing the possibility of applying for a new project lead role'`, `resolution_status='unclear'`, `customer_sentiment='neutral'`, `follow_up_required=False`. The model's notes field correctly observed the clip is a conversation between colleagues, not a customer support interaction. 1107 input / 74 output tokens, 4.4s.

---

### meeting_notes.py

**Status:** PASS

**Description:** Extracts `MeetingNotes` (attendees, topics, nested `ActionItem` list) from the conversation clip; instructions require attendees identifiable from the audio and explicitly assigned action items only.

**Result:** Returned `attendees=['Liam']`, `topics=['New project lead role opportunity']`, `action_items=[]` (none explicitly assigned in the clip, consistent with the instructions). 1101 input / 24 output tokens, 3.5s.

---
