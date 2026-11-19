# TEST_LOG

Verified against the live Sarvam API on 2026-11-18 with a standard Token Factory
key.

### basic.py

**Status:** PASS

**Description:** Sync, sync + streaming, async, and async + streaming runs with `sarvam-105b` and `reasoning_effort="none"`.

**Result:** All four variants returned responses (95s total).

---

### string_model.py

**Status:** PASS

**Description:** Agent created with `model="sarvam:gemma4"`.

**Result:** String syntax resolved to `Sarvam` and returned a response in 4.9s.

---

### structured_output.py

**Status:** PASS

**Description:** `output_schema=MovieScript` with `sarvam-105b` and `reasoning_effort="none"`, prompted with "Write a movie script set in New York."

**Result:** Returned a populated `MovieScript` in 3.4s.

---

### reasoning_agent.py

**Status:** PASS

**Description:** Logic puzzle with `reasoning_effort="high"` and `show_full_reasoning=True`.

**Result:** Returned a step-by-step solution with reasoning in 17.1s.

---

### tool_use.py

**Status:** PASS

**Description:** Local `get_weather` function with `sarvam-105b` at the default reasoning effort.

**Result:** Called the local tool and answered in 2.4s.

---

### test_sarvam.py

**Status:** PASS

**Description:** `pytest libs/agno/tests/unit/models/sarvam/` covers defaults, env-key loading, the missing-key error, client params, `reasoning_effort` passthrough, string resolution, dict round trips, and the `/v1` base URL override.

**Result:** 9 tests passed.
