# Test Log: 08_workflow

> Tested 2026-09-15 against `gpt-5.6-luna` (OpenAIResponses), demo venv, agno source tree.

### verify_step.py

**Status:** PASS

**Description:** Workflow [write -> Verify(on_fail="write", max_attempts=3, stop_on_unverified=True) -> publish]; the gate requires version 1.4.0 and an "## Upgrade notes" section the prompt never mentions, and RELEASE_NOTES.md is emptied at setup.

**Result:** Exit 0 on three runs. `Workflow status: COMPLETED`; `Step: verify | success: True` with `Segment step: write` nested under it, `Verification: verified / passed`, `Attempt 0: FAIL notes_complete`, `Attempt 1: PASS notes_complete`; then `Step: publish | success: True`. The verify step's content read `Verify verify: passed (2 attempts)` with no error, and the workflow content was the publisher's output: a one-sentence announcement on one run, while on another run the publisher repeated the release notes themselves. The unverified leg (S2/S3 content and error) is not exercised here, because the gate passed.

---
