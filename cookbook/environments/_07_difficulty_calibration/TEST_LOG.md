# Test Log - _07_difficulty_calibration

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Progressive arithmetic difficulty ladder with binary exact-answer scoring.

**Result:** `one-step` and `three-step` each passed 4/4 (1.00). Both
`edge-a` and `edge-b` passed 2/4 (0.50), producing a clear transition from
saturation to the learning zone.

---

### chained_arithmetic.py

**Status:** PASS

**Description:** Chained product, digit-sum, multiplication, and modulo verification.

**Result:** `product-only` passed 4/4 (1.00), `full-chain-a` 3/4 (0.75),
and `full-chain-b` 4/4 (1.00). Adding all four stages moved one row into the
middle band while the product-only anchor stayed saturated.

---

### ambiguity_ladder.py

**Status:** PASS

**Description:** Natural-language arithmetic whose grouping becomes increasingly ambiguous.

**Result:** `comma-scope`, `modifier-scope`, and `nested-scope` each passed
6/6 (1.00). `coordination-scope` passed 2/6 (0.33), showing that ambiguity in
ordinary prose can expose a boundary without larger operands.

---
