# Test Log: search_coordination

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python` (Python 3.12.9)
**Model:** OpenAI (gpt-4o, gpt-5.2)
**Services:** pgvector

## Structure Check

**Result:** Clean (0 violations)

---

## Runtime Results

### 01_coordinated_agentic_rag.py

**Status:** FAIL
**Time:** ~68s
**Description:** Coordinated agentic RAG with team search coordination.
**Output:** `HTTPStatusError: Redirect response '307 Temporary Redirect' for url 'https://docs.agno.com/basics/agents/overview.md'`
**Triage:** pre-existing (docs URL changed)

---

### 02_coordinated_reasoning_rag.py

**Status:** FAIL
**Time:** ~44s
**Description:** Coordinated reasoning RAG with team search coordination.
**Output:** `HTTPStatusError: Redirect response '307 Temporary Redirect' for url 'https://docs.agno.com/basics/agents/overview.md'`
**Triage:** pre-existing (docs URL changed)

---

### 03_distributed_infinity_search.py

**Status:** SKIP
**Time:** ~13s
**Description:** Distributed infinity search requiring infinity_client.
**Output:** `ImportError: infinity_client not installed`
**Triage:** infra

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_coordinated_agentic_rag.py | FAIL | pre-existing | docs.agno.com URL redirect |
| 02_coordinated_reasoning_rag.py | FAIL | pre-existing | docs.agno.com URL redirect |
| 03_distributed_infinity_search.py | SKIP | infra | infinity_client not installed |

**Totals:** 0 PASS, 2 FAIL, 1 SKIP, 0 ERROR
