# Test Log: 04_entity_memory

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o
**Services:** pgvector

## Structure Check

**Result:** Checked 2 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_facts_and_events.py

**Status:** PASS
**Time:** ~35s
**Description:** Entity memory with facts and events. Acme Corp tracked with funding round and hiring events. Sequoia relationship stored.
**Output:** Entity created with facts, events added, relationship to Sequoia persisted.
**Triage:** n/a

---

### 02_entity_relationships.py

**Status:** PASS
**Time:** ~35s
**Description:** Entity relationships. DataPipe-BigCloud partnership and London office expansion tracked. Agentic tools used for entity management.
**Output:** Entities created with relationships, search_entities and add_relationship tools called.
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_facts_and_events.py | PASS | n/a | Acme Corp entity with events |
| 02_entity_relationships.py | PASS | n/a | Cross-entity relationships via tools |

**Totals:** 2 PASS, 0 FAIL, 0 SKIP, 0 ERROR
