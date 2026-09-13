# Test Log - _11_audio_transcription

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Verbatim transcript of `QA-01.mp3` (English family Q&A clip) into a flat `Transcript` schema with a single `text` field.

**Result:** Full clean transcript returned, starting "How many people are there in your family? There are five people in my family..." and ending "...My mom always prepares delicious meals for us." Tokens: input=1949, output=1488; duration 8.23s.

---

### with_diarization.py

**Status:** PASS

**Description:** Transcript of `sample_conversation.wav` split into speaker turns via the `DiarizedTranscript` schema, with generic speaker identifiers.

**Result:** Five turns returned alternating between exactly two speakers, labeled consistently as "Speaker A" and "Speaker B" (A opens with "Hello, Liam, hey..." and closes with "...Thanks for the encouragement."). No invented names. Duration 3.38s.

---

### with_timestamps.py

**Status:** PASS

**Description:** Transcript of `QA-01.mp3` split into sentence-level segments with start/end times in seconds via the `TimedTranscript` schema.

**Result:** 25 segments returned from 0.0 to 116.0 with monotonically non-decreasing times, e.g. [0.0, 2.1] "How many people are there in your family?". Known model quirk observed: past the one-minute mark the model flattens mm:ss into decimal (59.3 jumps to 103.3, i.e. 1:03.3 read as 103.3 seconds), so absolute values after 60s are inflated while ordering stays correct.

---
