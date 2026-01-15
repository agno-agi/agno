# Bug Report: #5968 - content_hash Calculated from Source, Not Content

## Summary

The `content_hash` field is misleadingly named and miscalculated. It hashes source identifiers (name/URL/path) instead of actual document content, causing `skip_if_exists=True` to incorrectly skip content updates.

## Status: CONFIRMED (Design Issue)

## Code Location

- **Primary:** `libs/agno/agno/knowledge/knowledge.py:2356-2414` (`_build_content_hash`)
- **Skip logic:** `libs/agno/agno/knowledge/knowledge.py:1090-1108` (`_should_skip`)
- **Affected:** All VectorDB adapters store this hash in `content_hash` column

## Root Cause

```python
def _build_content_hash(self, content: Content) -> str:
    hash_parts = []
    if content.name:
        hash_parts.append(content.name)        # ← Metadata only
    if content.description:
        hash_parts.append(content.description) # ← Metadata only
    if content.path:
        hash_parts.append(str(content.path))   # ← Source identifier
    elif content.url:
        hash_parts.append(content.url)         # ← Source identifier
    # ... NO actual text content!
```

The hash is calculated BEFORE content is read (for performance), so it can only use metadata.

## Reproduction

```python
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.content import Content

knowledge = Knowledge(name="Test", vector_db=None)

# Same source = Same hash (regardless of actual content)
content_v1 = Content(name="report.pdf")
content_v2 = Content(name="report.pdf")

hash_v1 = knowledge._build_content_hash(content_v1)
hash_v2 = knowledge._build_content_hash(content_v2)

assert hash_v1 == hash_v2  # COLLISION! Different content, same hash
```

## Failure Scenarios

| Scenario | Expected | Actual |
|----------|----------|--------|
| Same URL, content updated | Re-ingest new content | ❌ Skipped |
| Same filename, different files | Store both | ❌ Second skipped |
| Different URLs, same content | Deduplicate | ❌ Both stored |

## Impact

- Web pages that update are never re-ingested
- File updates are silently ignored
- True duplicates from different sources are not detected

## Proposed Fixes

### Option A: Hash After Reading (Breaking Change)
Calculate hash from actual document text after reading. Performance cost: must read before skip decision.

### Option B: Two-Level Hash (Recommended)
- `source_hash`: Current behavior (fast, for source tracking)
- `content_hash`: New field (hash of actual text, for deduplication)

### Option C: Rename for Clarity (Minimal)
Rename `content_hash` → `source_hash` everywhere. Document that `skip_if_exists` skips by SOURCE.

## Test Files

- `/tmp/claude/test_issue_5968_v3.py` - Design analysis demonstration

## Related Issues

- Affects all VectorDB adapters (pgvector, ChromaDB, Qdrant, etc.)
- User expectation: `skip_if_exists` should deduplicate by CONTENT
- Current behavior: `skip_if_exists` deduplicates by SOURCE

## References

- GitHub Issue: https://github.com/agno-agi/agno/issues/5968
- Reporter: @shlemov-max
- Agno Version: 2.3.22+
