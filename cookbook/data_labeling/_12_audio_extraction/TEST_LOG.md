# Test Log - _12_audio_extraction

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### basic.py

**Status:** PASS

**Description:** Extract a generic `CallSummary` (caller intent, key topics, next action) from a conversation clip.

**Result:** Caller intent and next action captured; key topics list is coherent.

---

### call_summary.py

**Status:** PASS

**Description:** Extract a domain-shaped `SupportCall` (issue, resolution status, sentiment, follow-up).

**Result:** All fields populated with sensible values.

---

### meeting_notes.py

**Status:** PASS

**Description:** Extract `MeetingNotes` (attendees, topics, action items) from a conversation clip.

**Result:** Attendees and topics extracted; action_items empty since none were stated in this clip.

---
