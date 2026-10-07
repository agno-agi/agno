# MCP reliability sidecar

This example wraps a synthetic external create operation with a remote MCP
reliability sidecar. It is deterministic, does not call a model, and requires no
account or API key.

It demonstrates two failure paths:

1. A failed checkpoint generation is recovered by another worker.
2. An external create succeeds but its response is lost. The retry searches a
   stable marker and verifies the existing record instead of creating a
   duplicate.

The sidecar coordinates opaque identifiers only. The synthetic record stays
local, and only an HMAC fingerprint of the caller's readback evidence is sent.
The final `external_proof: false` is intentional: the checkpoint records the
caller's assertion but cannot prove what happened in another system.

## Run

From the repository root:

```bash
uv run --with "agno[mcp]" python cookbook/91_tools/mcp/reliability_sidecar/recovery_and_duplicate_resistance.py
```

Expected summary:

```json
{
  "planned_guarantee": "duplicate-resistant",
  "recovered_generation": 2,
  "competing_worker_admitted": false,
  "external_create_attempts": 1,
  "matching_records": 1,
  "final_stage": "caller_verified",
  "external_proof": false
}
```

## What this does not guarantee

- It is duplicate-resistant, not exactly-once.
- Sidecar state is not proof of external completion.
- There is no transaction spanning the sidecar and the destination.
- A real integration must provide strong stable-marker search before using this
  recovery pattern.

The endpoint used by the example is
`https://liberated.site/mcp?source=agno-cookbook-reliability`.
