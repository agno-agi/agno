# Test Log

## 2026-08-26 — gpt-5.5, demo venv

### verified_tool.py

**Status:** PASS

**Description:** A counter tool with a hidden cap of +5 per call, decorated with @verified_tool. The model predicted the first call would land on 17; the cap advanced it only to 5; the divergence block reported expected 17 / actual 5; the model replanned from the real value (5 -> 10 -> 15 -> 17) and reached the target in capped steps, then stated what it learned about the tool's behavior.

**Result:** Success — the prediction contract turned a silent wrong assumption into an immediate, evidence-based correction.

---
