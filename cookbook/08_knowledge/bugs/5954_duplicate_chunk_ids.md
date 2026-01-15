# Bug Report: #5954 - Duplicate chunk_id in DocumentChunking

## Summary

The `DocumentChunking` class was not incrementing `chunk_number` after each chunk, causing all chunks to have the same ID (e.g., `doc_id_1`). This caused unique constraint violations when inserting into PostgreSQL/pgvector.

## Status: ALREADY FIXED

**Fixed in:** Commit `286b55c83` - PR #5916 (Jan 12, 2026)
**Fixes:** Issue #5915

## Root Cause

In the old code (commit `b1d627bb` and earlier):

```python
# OLD CODE - BUGGY
chunk_number = 1

for para in paragraphs:
    # ... logic ...
    if current_chunk:
        chunks.append(
            Document(
                id=f"{document.id}_{chunk_number}",  # Always _1
                ...
            )
        )
        # ❌ NO chunk_number += 1 HERE!
    current_chunk = [para]
    current_size = para_size

if current_chunk:
    chunks.append(
        Document(
            id=f"{document.id}_{chunk_number}",  # Still _1!
            ...
        )
    )
```

**Result:** Every chunk got `chunk_number=1`, so all chunk IDs were identical (e.g., `doc_id_1`, `doc_id_1`, `doc_id_1`).

## The Fix (PR #5916)

Added `chunk_number += 1` after each `chunks.append()`:

```python
# NEW CODE - FIXED
if current_chunk:
    chunks.append(Document(...))
    chunk_number += 1  # ✅ Now incremented!
```

Current locations where chunk_number is incremented:
- `document.py:55` - After oversized paragraph chunk
- `document.py:84` - After sentence split chunk
- `document.py:102` - After normal paragraph chunk

## Verification

Test script confirms fix works:
```bash
$ python test_issue_5954.py

Total chunks created: 3
Unique chunk IDs: 3
All chunk IDs are unique (no bug found)

Chunk IDs:
  1: test-pptx-123_1
  2: test-pptx-123_2
  3: test-pptx-123_3
```

## Affected Users

Users on Agno version < 2.3.24 (before commit `286b55c83`) may experience this bug.

**Solution:** Upgrade to latest Agno version.

## Files Changed in Fix

- `libs/agno/agno/knowledge/chunking/document.py`
  - Added `chunk_number += 1` at lines 55, 84, 102
  - Added sentence splitting for oversized paragraphs

## References

- GitHub Issue: https://github.com/agno-agi/agno/issues/5954
- Fix PR: https://github.com/agno-agi/agno/pull/5916
- Related Issue: #5915
