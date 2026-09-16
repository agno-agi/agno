# Test Log — feedback_labeler

Tested September 16, 2026 with a fresh Python 3.14.5 environment installed from
this directory's `requirements.txt`: published Agno 3.0.8 and OpenAI 3.14.1.
Live calls used `gpt-5.6`, synthetic inputs, and disposable local storage.

### demo.py

**Status:** PASS

**Description:** Run the documented demo with the live model.

**Result:** The live batch retained all three input IDs and produced `bug`, `feature_request`, and `needs_review`. The initial policy chose bug for mixed praise and a bug; after explicitly requiring review when multiple categories apply, the rerun produced the expected review record. These are smoke observations, not an accuracy evaluation.

---

No hosted deployment or production integration was tested.
