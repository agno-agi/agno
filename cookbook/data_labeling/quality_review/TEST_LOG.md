# Test Log - quality_review

Tested 2026-05-17 against `gpt-5.5` (OpenAIResponses) for labeler A / reviewer / adjudicator and `claude-sonnet-4-5` (Claude) for labeler B, agno 2.6.6.

### basic.py

**Status:** PASS

**Description:** End-to-end labeler / reviewer / adjudicator pipeline on a Contact extraction task. Two labelers (different providers) extract, a reviewer diffs them, an adjudicator runs only if there's disagreement.

**Result:** Labelers agreed; reviewer returned `needs_adjudication=False`; final label returned with `notes='Labelers agreed.'` (adjudicator path not exercised on this input — covered by the original invoice cookbook in git history).

---
