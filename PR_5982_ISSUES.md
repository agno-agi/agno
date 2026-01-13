# PR #5982 Issues Tracker

**PR**: https://github.com/agno-agi/agno/pull/5982
**Title**: feat: Knowledge rework
**Analysis Date**: 2026-01-13
**Status**: VERIFIED

---

## Summary

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 1 | Runtime error - method doesn't exist |
| HIGH | 4 | Missing backwards compatibility wrappers |
| MEDIUM | 2 | Test mocks wrong + auth param dropped |

**Total Verified Bugs: 7**
**Status: ALL FIXED**

---

## CRITICAL Issues

### C1. agent.py - Wrong method name (VERIFIED BUG)

- **File**: `libs/agno/agno/agent/agent.py`
- **Line**: 9552
- **Current**: `await self.knowledge.async_validate_filters(filters)`
- **Fix**: `await self.knowledge.avalidate_filters(filters)`
- **Impact**: `AttributeError` at runtime - method `async_validate_filters()` does not exist
- **Verification**: Knowledge class has `avalidate_filters()` at line 757, NOT `async_validate_filters()`
- **Status**: [x] FIXED

---

## HIGH Issues (Missing Backwards Compatibility)

### H1. Missing `add_contents()` wrapper (VERIFIED BUG)

- **File**: `libs/agno/agno/knowledge/knowledge.py`
- **Missing Method**: `add_contents()` (sync, plural)
- **Should Delegate To**: `insert_many()`
- **Verification**: Method does not exist - searched entire file
- **Status**: [x] FIXED

### H2. Missing `async_search()` wrapper (VERIFIED BUG)

- **File**: `libs/agno/agno/knowledge/knowledge.py`
- **Missing Method**: `async_search()`
- **Should Delegate To**: `asearch()`
- **Verification**: Method does not exist - only `asearch()` exists at line 507
- **Status**: [x] FIXED

### H3. Missing `async_get_valid_filters()` wrapper (VERIFIED BUG)

- **File**: `libs/agno/agno/knowledge/knowledge.py`
- **Missing Method**: `async_get_valid_filters()`
- **Should Delegate To**: `aget_valid_filters()`
- **Verification**: Method does not exist - only `aget_valid_filters()` exists at line 736
- **Status**: [x] FIXED

### H4. Missing `async_validate_filters()` wrapper (VERIFIED BUG)

- **File**: `libs/agno/agno/knowledge/knowledge.py`
- **Missing Method**: `async_validate_filters()`
- **Should Delegate To**: `avalidate_filters()`
- **Verification**: Method does not exist - only `avalidate_filters()` exists at line 757
- **Status**: [x] FIXED

---

## MEDIUM Issues

### M1. test_knowledge.py - Mock patches wrong method (VERIFIED BUG)

- **File**: `libs/agno/tests/integration/os/test_knowledge.py`
- **Lines**: 54, 313, 343
- **Current**: `mock_knowledge.async_get_valid_filters`
- **Fix**: `mock_knowledge.aget_valid_filters`
- **Verification**: Knowledge class method is `aget_valid_filters()` not `async_get_valid_filters()`
- **Impact**: Tests pass but mocks don't intercept actual method calls
- **Status**: [x] FIXED

### M2. insert_many/ainsert_many - auth parameter not passed (VERIFIED BUG)

- **File**: `libs/agno/agno/knowledge/knowledge.py`
- **Issue**: `insert()` accepts `auth` param (line 94), `ainsert()` accepts `auth` param (line 177)
- **Bug**: `insert_many()` and `ainsert_many()` never pass `auth` to internal calls
- **Locations**:
  - `insert_many()`: lines 377, 408, 420, 434, 446, 459 - all missing `auth=argument.get("auth")`
  - `ainsert_many()`: lines 235, 266, 278, 292, 304, 317 - all missing `auth=argument.get("auth")`
- **Impact**: Auth credentials silently dropped when using batch insert methods
- **Status**: [x] FIXED

---

## NOT BUGS (Verified Working)

These were initially flagged but are **NOT bugs**:

### learned_knowledge.py lines 935, 1014
- **Uses**: `self.knowledge.add_content(...)`
- **Status**: ✅ WORKS - `add_content()` is a deprecated wrapper that correctly delegates to `insert()`
- **Action**: Optional update to new API for consistency, but not required

### cookbook files (code_chunking.py, code_chunking_custom_tokenizer.py)
- **Uses**: `knowledge.add_content(...)`
- **Status**: ✅ WORKS - deprecated wrapper functions correctly
- **Action**: Optional update to new API for consistency, but not required

---

## Pre-existing Bugs (Not Introduced by PR)

### learned_knowledge.py line 1005-1006
- **Code**: `hasattr(self.knowledge, "aadd_content")` and `await self.knowledge.aadd_content(...)`
- **Issue**: `aadd_content` method NEVER existed in any version
- **Status**: Pre-existing bug, not introduced by this PR

---

## Fix Plan

### Step 1: Fix Critical Bug

**agent.py line 9552:**
```python
# Change:
valid_filters, invalid_keys = await self.knowledge.async_validate_filters(filters)  # type: ignore
# To:
valid_filters, invalid_keys = await self.knowledge.avalidate_filters(filters)  # type: ignore
```

### Step 2: Add Missing Deprecated Wrappers

In `libs/agno/agno/knowledge/knowledge.py`, add:

```python
def add_contents(self, *args, **kwargs):
    """DEPRECATED: Use `insert_many()` instead."""
    import warnings
    warnings.warn("add_contents() is deprecated. Use insert_many() instead.", DeprecationWarning, stacklevel=2)
    return self.insert_many(*args, **kwargs)

async def async_search(self, *args, **kwargs):
    """DEPRECATED: Use `asearch()` instead."""
    import warnings
    warnings.warn("async_search() is deprecated. Use asearch() instead.", DeprecationWarning, stacklevel=2)
    return await self.asearch(*args, **kwargs)

async def async_get_valid_filters(self):
    """DEPRECATED: Use `aget_valid_filters()` instead."""
    import warnings
    warnings.warn("async_get_valid_filters() is deprecated. Use aget_valid_filters() instead.", DeprecationWarning, stacklevel=2)
    return await self.aget_valid_filters()

async def async_validate_filters(self, filters):
    """DEPRECATED: Use `avalidate_filters()` instead."""
    import warnings
    warnings.warn("async_validate_filters() is deprecated. Use avalidate_filters() instead.", DeprecationWarning, stacklevel=2)
    return await self.avalidate_filters(filters)
```

### Step 3: Fix Test Mocks

**test_knowledge.py lines 54, 313, 343:**
```python
# Change all occurrences of:
async_get_valid_filters
# To:
aget_valid_filters
```

### Step 4: Fix auth Parameter in Batch Methods

In `insert_many()` and `ainsert_many()`, add to ALL internal `insert()`/`ainsert()` calls:
```python
auth=argument.get("auth"),
```

---

## Verification Commands

```bash
./scripts/format.sh
./scripts/validate.sh
pytest libs/agno/tests/integration/os/test_knowledge.py -v
```

---

## Changelog

- 2026-01-13: Initial analysis - 17 issues found
- 2026-01-13: Deep analysis - expanded to 40+ potential issues
- 2026-01-13: Verification pass - refined to 7 actual bugs
  - Removed false positives (deprecated but working code)
  - Confirmed real bugs via code inspection
