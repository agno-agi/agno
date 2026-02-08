# Restructuring Plan: `cookbook/08_learning/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Directories | 12 (1 root + 10 numbered subdirectories + 1 `__init__.py`) |
| Total `.py` files (non-`__init__`) | 31 |
| Fully style-compliant | 0 (~0%) — banners use `====` not `----` |
| Have module docstring | 31 (100%) |
| Have section banners | 26 (84%) — but wrong format (equals signs, not dashes) |
| Have `if __name__` gate | 31 (100%) |
| Contain emoji | 0 (0%) |
| Subdirectories with README.md | 1 / 12 (root only) |
| Subdirectories with TEST_LOG.md | 1 / 12 (root only) |

### Key Problems

1. **Wrong banner format.** 26 files use `# ============================================================================` instead of the standard `# ---------------------------------------------------------------------------`. The remaining 5 files (3 in `00_quickstart/`, 2 in `09_decision_logs/`) have no banners at all.

2. **No subdirectory documentation.** Only the root has README.md and TEST_LOG.md. All 10 subdirectories lack both.

3. **Naming inconsistency in `09_decision_logs/`.** Uses single-digit prefixes (`1_`, `2_`) instead of the standard double-digit (`01_`, `02_`) pattern used everywhere else.

### Overall Assessment

This is the **best-structured cookbook section** in the entire repository. Every file has a docstring and main gate. 84% already have section banners (wrong format). The work is almost entirely:
1. Convert `====` banners to `----` banners
2. Add banners to the 5 files missing them
3. Add README.md and TEST_LOG.md to all subdirectories
4. Fix naming in `09_decision_logs/`

**No file merges, cuts, or moves needed.**

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 31 | 31 (no change) |
| Style compliance | 0% | 100% |
| README coverage | 1/12 | All directories |
| TEST_LOG coverage | 1/12 | All directories |

---

## 2. Proposed Directory Structure

No structural changes needed. The directory is already well-organized.

```
cookbook/08_learning/
├── 00_quickstart/           # Quick intro (always, agentic, learned knowledge)
├── 01_basics/               # Core concepts (user profile, memory, session, entity, knowledge)
├── 02_user_profile/         # Deep dive: user profile extraction modes
├── 03_session_context/      # Deep dive: session context strategies
├── 04_entity_memory/        # Deep dive: entity facts, events, relationships
├── 05_learned_knowledge/    # Deep dive: agentic and propose modes
├── 06_quick_tests/          # Quick smoke tests (async, shorthand, graceful, Claude)
├── 07_patterns/             # Real-world patterns (personal assistant, support agent)
├── 08_custom_stores/        # Custom memory store implementations
└── 09_decision_logs/        # Decision logging (basic, always mode)
```

---

## 3. File Disposition Table

### `00_quickstart/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_always_learn.py` | **KEEP + FIX** | Add section banners (currently missing) |
| `02_agentic_learn.py` | **KEEP + FIX** | Add section banners (currently missing) |
| `03_learned_knowledge.py` | **KEEP + FIX** | Add section banners (currently missing) |

---

### `01_basics/` (9 → 9, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `1a_user_profile_always.py` | **KEEP + FIX** | Convert `====` banners to `----` |
| `1b_user_profile_agentic.py` | **KEEP + FIX** | Convert banners |
| `2a_user_memory_always.py` | **KEEP + FIX** | Convert banners |
| `2b_user_memory_agentic.py` | **KEEP + FIX** | Convert banners |
| `3a_session_context_summary.py` | **KEEP + FIX** | Convert banners |
| `3b_session_context_planning.py` | **KEEP + FIX** | Convert banners |
| `4_learned_knowledge.py` | **KEEP + FIX** | Convert banners |
| `5a_entity_memory_always.py` | **KEEP + FIX** | Convert banners |
| `5b_entity_memory_agentic.py` | **KEEP + FIX** | Convert banners |

---

### `02_user_profile/` (3 → 3, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_always_extraction.py` | **KEEP + FIX** | Convert banners |
| `02_agentic_mode.py` | **KEEP + FIX** | Convert banners |
| `03_custom_schema.py` | **KEEP + FIX** | Convert banners |

---

### `03_session_context/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_summary_mode.py` | **KEEP + FIX** | Convert banners |
| `02_planning_mode.py` | **KEEP + FIX** | Convert banners |

---

### `04_entity_memory/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_facts_and_events.py` | **KEEP + FIX** | Convert banners |
| `02_entity_relationships.py` | **KEEP + FIX** | Convert banners |

---

### `05_learned_knowledge/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_agentic_mode.py` | **KEEP + FIX** | Convert banners |
| `02_propose_mode.py` | **KEEP + FIX** | Convert banners |

---

### `06_quick_tests/` (4 → 4, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_async_user_profile.py` | **KEEP + FIX** | Convert banners |
| `02_learning_true_shorthand.py` | **KEEP + FIX** | Convert banners |
| `03_no_db_graceful.py` | **KEEP + FIX** | Convert banners |
| `04_claude_model.py` | **KEEP + FIX** | Convert banners |

---

### `07_patterns/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `personal_assistant.py` | **KEEP + FIX** | Convert banners |
| `support_agent.py` | **KEEP + FIX** | Convert banners |

---

### `08_custom_stores/` (2 → 2, no change)

| File | Disposition | Rationale |
|------|------------|-----------|
| `01_minimal_custom_store.py` | **KEEP + FIX** | Convert banners |
| `02_custom_store_with_db.py` | **KEEP + FIX** | Convert banners |

---

### `09_decision_logs/` (2 → 2, rename for consistency)

| File | Disposition | New Name | Rationale |
|------|------------|----------|-----------|
| `1_basic_decision_log.py` | **KEEP + RENAME + FIX** | `01_basic_decision_log.py` | Add leading zero. Add section banners (currently missing) |
| `2_decision_log_always.py` | **KEEP + RENAME + FIX** | `02_decision_log_always.py` | Add leading zero. Add section banners (currently missing) |

---

## 4. New Files Needed

No new files needed. Coverage is comprehensive.

---

## 5. Missing READMEs and TEST_LOGs

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `08_learning/` (root) | EXISTS | EXISTS (update) |
| `00_quickstart/` | **MISSING** | **MISSING** |
| `01_basics/` | **MISSING** | **MISSING** |
| `02_user_profile/` | **MISSING** | **MISSING** |
| `03_session_context/` | **MISSING** | **MISSING** |
| `04_entity_memory/` | **MISSING** | **MISSING** |
| `05_learned_knowledge/` | **MISSING** | **MISSING** |
| `06_quick_tests/` | **MISSING** | **MISSING** |
| `07_patterns/` | **MISSING** | **MISSING** |
| `08_custom_stores/` | **MISSING** | **MISSING** |
| `09_decision_logs/` | **MISSING** | **MISSING** |

---

## 6. Recommended Cookbook Template

This section already follows best practices. The only change is converting banner format:

**Before:**
```python
# ============================================================================
# Setup
# ============================================================================
```

**After:**
```python
# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup → Create Agent/Config → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable

### Best Current Examples (reference)

All files in `01_basics/` through `08_custom_stores/` are excellent examples — they just need the banner format update.
