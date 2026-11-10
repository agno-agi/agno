# Test Log: scylladb

> The storage layer used by these examples — `DynamoDb(db_client=<boto3 Alternator client>)`
> — was validated against a local ScyllaDB Alternator container
> (`scylladb/scylla:latest`, `--alternator-port 8000 --alternator-write-isolation=only_rmw_uses_lwt`):
> table creation with GSIs, session upsert/get/list/rename/delete, user-memory
> upsert/get/list, topic scan, and metrics calculation all pass (13/13).
>
> The full scripts below additionally require an `OPENAI_API_KEY` to exercise the LLM.

### scylladb_for_agent.py

**Status:** PENDING

**Description:** ScyllaDB (Alternator) storage path for an agent. Storage layer verified
against a local Alternator container; full end-to-end run requires an LLM API key.

**Result:** Storage CRUD verified (13/13). LLM run not yet executed in this environment.

---

### scylladb_for_team.py

**Status:** PENDING

**Description:** ScyllaDB (Alternator) storage path for a team. Storage layer verified
against a local Alternator container; full end-to-end run requires an LLM API key.

**Result:** Storage CRUD verified (13/13). LLM run not yet executed in this environment.

---

### scylladb_for_workflow.py

**Status:** PENDING

**Description:** ScyllaDB (Alternator) storage path for a workflow. Storage layer verified
against a local Alternator container; full end-to-end run requires an LLM API key.

**Result:** Storage CRUD verified (13/13). LLM run not yet executed in this environment.

---
