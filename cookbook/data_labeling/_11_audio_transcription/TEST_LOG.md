# Test Log - _11_audio_transcription

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### basic.py

**Status:** PASS

**Description:** Verbatim transcript from `QA-01.mp3` (English Q&A).

**Result:** Clean transcript of the full clip.

---

### with_diarization.py

**Status:** PASS

**Description:** Transcript split into speaker turns over `sample_conversation.wav`.

**Result:** Two speakers identified with five turns; speaker labels are consistent across turns.

---

### with_timestamps.py

**Status:** PASS

**Description:** Transcript with `[start, end]` second timestamps per segment.

**Result:** Segments returned with monotonically increasing timestamps.

---
