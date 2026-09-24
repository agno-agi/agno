# Test Log - _27_verified_dataset

Tested 2026-07-20 against `gpt-5.5` through `OpenAIResponses`, Agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Passing-only SFT export from binary learning-zone tasks.

**Result:** Live run completed 8/8 scored attempts in 51 seconds.
`rounds-eight` passed 3/4 (0.75) and `rounds-nine` 1/4 (0.25). Both tasks were
selected, and passing-only export wrote four verified conversations. No
training occurred.

---

### curate_learning_zone.py

**Status:** PASS

**Description:** Async strict partial-rate curation and passing-only export.

**Result:** Async live run completed 12/12 scored attempts in 53 seconds.
`easy-anchor` passed 4/4 (1.00), `rounds-eight` 3/4 (0.75), and `rounds-ten`
2/4 (0.50). The strict partial-rate filter selected the latter two rows, and
`ato_sft_jsonl()` wrote five passing conversations.

---

### export_manifest.py

**Status:** PASS

**Description:** Dataset export with provenance inspection and a SHA-256 manifest.

**Result:** Live run completed 8/8 scored attempts in 56 seconds.
`rounds-nine` passed 1/4 (0.25) and `rounds-ten` 2/4 (0.50). Export wrote
three verified conversations, and the manifest recorded dataset SHA-256
`cb1c8090db0c9f58d5fb3869859e4d57df915ecc6f92091f089d5e1b7c373dbb`
alongside both fingerprints and selected task ids.

---
