# Shipping fixture verification

### Read-only harness exercises — 2026-10-09

**Status:** PASS

**Description:** Claude and Codex read shipping.py and orders.json through their actual tools, both standalone and through AgentOS HTTP.

**Result:** Both explained small=8, boundary=0 and large=0. The integration suite compared all fixture-file hashes before and after every case; they remained unchanged. This fixture is input data, not a runnable agent cookbook.
