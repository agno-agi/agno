# Test Log - _18_quality_review

Tested 2026-07-18 against `gemini-3.5-flash` (labeler A) and `claude-opus-4-7` (labeler B, reviewer, adjudicator), agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Labeler / reviewer / adjudicator pipeline expressed as an agno Workflow (Parallel labelers, reviewer, Condition-gated adjudicator) on a Contact extraction task. The demo runs two inputs - a clean one and one with deliberately conflicting details - and prints the full step trail for both, exercising both the skip path and the adjudication path.

**Result:** Clean input: both labelers returned identical Contact objects (name='Liam Ortega', email='liam@meadow.io', company='Meadow', title='Support Engineer'), the reviewer returned needs_adjudication=False, and the trail shows the Condition skip ('Condition Adjudicate not met - skipped 1 steps'). Conflicting input: the labelers disagreed on name ('Dr. Sarah Chen-Watanabe' vs 'Sarah Chen') and title ('Principal Scientist and acting Head of Platform' vs 'Principal Scientist'); the reviewer flagged both fields with per-field reasons; the adjudicator ran and emitted FinalLabel(contact=Contact(name='Sarah Chen', email='s.chen@nova-labs.io', phone='+1-415-555-0177', company='NovaLabs', title='Principal Scientist and acting Head of Platform')). Which fields disagree can vary run to run; the conflicting input is constructed so that at least one field reliably does.

---
