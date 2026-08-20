# TEST_LOG


## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| basic.py | PARTIAL-BUG | 3 of 4 invocations pass; second asyncio.run fails 'Event loop is closed' - unguarded cached async client in agno.models.cohere (also ollama, huggingface, bedrock); tracked for fix |

---

No cookbook tests have been recorded for this directory yet.
