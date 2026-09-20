# TEST_LOG

Provider: TypeSafe (`https://api.typesafe.ai`), env var `TYPESAFE_API_KEY`, default model `jev-latest` (resolved to `jev-1.13.0`).

**Tested:** 2026-09-21
**Environment:** `.venv/Scripts/python.exe` (Windows, Python 3.12, typesafe-sdk 0.7.0), live API

---

### basic.py

**Status:** PASS

**Description:** Fills an `output_schema` with a Literal (choice with option descriptions), a bool (noul) and an IntEnum (score) for a support ticket, then prints `model_provider_data`.

**Result:** Returned `Triage(department='technical', is_urgent=True, frustration=frustrated)`. Choice confidence 1.0, urgency noul 0.98, 445 input / 73 output tokens. Without the option descriptions the same kind of ticket was routed with confidence 0.59, so the `criteria` channel matters.

---

### async_basic.py

**Status:** PASS

**Description:** Classifies three product reviews concurrently with `arun` on one reused agent, including a `List[Literal]` field that fans out into one noul per topic.

**Result:** All three returned parsed `Review` objects with sensible sentiment and topics. The neutral review ("It works. Nothing special, nothing wrong.") came back with a lowest confidence of 0.31, which is the intended signal for an ambiguous input.

---

### raw_questions.py

**Status:** PASS

**Description:** Asks raw noul, choice and score questions with `Jev(questions=...)`, with the agent instructions reaching Jev as `context`.

**Result:** `refund_requested` 0.98, `policy_allows_refund` 0.98 (read from the instructions), next step `refund` at 0.76, effort 0.24. The code-side threshold printed "refund automatically".

---

### tool_use.py

**Status:** PASS

**Description:** Closed-set tool calling over three smart-home tools, with a generative `fallback_models` entry for requests no tool fits.

**Result:** Four commands produced the right tool and arguments, including an optional argument left to its default, an optional argument filled when stated, and a `List[Literal]` argument (`["front", "garage"]`). The non-command ("What is a good name for a smart home?") failed over to `gpt-5.6-luna`, which answered.

---
