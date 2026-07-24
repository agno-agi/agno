# Test Log - _05_operations

Tested 2026-07-24, agno 2.8.0 (source tree, branch feat/agent-fs). No model, no API keys — both files are pure Python against the store.

### quota_recovery.py

**Status:** PASS

**Description:** Hits the per-file cap and the namespace cap on purpose (caps shrunk to 200/300 bytes), prints the typed errors and the exact tool strings an agent would see, then recovers by partitioning and by deleting the oldest partition.

**Result:** Per-file cap: typed error `file 209 > 200`, tool string "Error: seen/2026-07-22.md would be 209 bytes (limit 200 per file). Start a new file (for record logs, partition by date, e.g. seen/2026-07-24.md) or delete files you no longer need." — recovery 1 wrote the record to a new partition. Namespace cap: typed error `namespace 284 of 300`, tool string "Error: storage is full (284 of 300 bytes). Delete files you no longer need (see list_files), then retry." — recovery 2 deleted the oldest partition (3 files/284 bytes -> 2 files/133 bytes) and the retried append succeeded.

---

### inspect_namespace.py

**Status:** PASS

**Description:** Attaches to an agent's namespace from a plain script: lists files with sizes and versions, reads working state, seeds seen-records, and verifies them with contains().

**Result:** Listing showed `seen/2026-07-23.md 39B v1` and `state/last-run.md 30B v1`, usage `{'files': 2, 'bytes': 69}`. Read back "2026-07-23: briefed 3 stories". After seeding two more ids, the membership check returned `{'found': ['kite-os-release'], 'missing': ['brand-new-story']}` — the agent's next run will skip everything in found.

---
