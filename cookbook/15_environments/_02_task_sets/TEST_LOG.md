# Test Log - _02_task_sets

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Inline tasks with stable ids and expected values at K=4.

**Result:** Final live run completed with 12/12 scored attempts and no unscored attempts. Observed rates: `easy-product` 4/4 (1.00), `chained-product-a` 1/4 (0.25), `dual-chain-sum` 0/4 (0.00). The first calibration saturated its easy row and both standalone chained rows at 4/4, so one standalone row was replaced by the compound two-chain task and the file was rerun.

---

### from_jsonl.py

**Status:** PASS

**Description:** Strict JSONL loading of three task rows at K=4.

**Result:** Live run loaded all three checked-in JSONL rows, scored 12/12 attempts, and had no unscored attempts. Observed rates: `easy-product` 4/4 (1.00), `chained-product-a` 3/4 (0.75), `dual-chain-sum` 0/4 (0.00). The standalone chained row supplied the true partial band.

---

### with_metadata.py

**Status:** PASS

**Description:** Runs the two original task objects tagged as calibration rows at K=4.

**Result:** Final live run selected two original task objects by metadata, scored 8/8 attempts, and had no unscored attempts. Observed rates: `chained-product-a` 3/4 (0.75) and `chained-product-b` 3/4 (0.75). The first metadata slice produced only 4/4 and 0/4 rows; it was recalibrated to include two independent middle candidates before this run.

---
