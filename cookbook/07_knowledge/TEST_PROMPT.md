# Knowledge Cookbooks Test Prompt

## Goal

Run all knowledge cookbook examples and record results in TEST_LOG.md.

## Context

Read these files first:
- `cookbook/07_knowledge/README.md` - Overview and structure
- `CLAUDE.md` - Testing workflow and conventions

## Environment

```bash
# Virtual environment
.venvs/demo/bin/python

# Setup (if needed)
./scripts/demo_setup.sh

# Database
./cookbook/scripts/run_qdrant.sh

# Required env vars
export OPENAI_API_KEY=your-key
```

## Execution

1. Run each cookbook file in order (01_getting_started first, then 02_building_blocks, etc.)
2. For each file, record:
   - Status: PASS or FAIL
   - Description: What was tested
   - Result: Summary of output or error
3. Skip files that require credentials you don't have (cloud integrations)
4. Skip files that require optional packages not installed

## Special Cases

- **Cloud integrations** (05_integrations/cloud/): Require provider credentials. Mark as SKIP if not available.
- **Managed vector DBs** (05_integrations/vector_dbs/03_managed.py): Requires Pinecone/Qdrant accounts. Mark as SKIP.
- **Graph RAG** (04_advanced/03_graph_rag.py): Requires lightrag-agno. Mark as SKIP if not installed.
- **Reranking** (02_building_blocks/03_reranking.py): Requires COHERE_API_KEY.

## Validation

After testing, verify:
- All PASS files ran without errors
- TEST_LOG.md is updated with results
- No deprecated API usage (add_content, add_content_async)

## Response Format

Update TEST_LOG.md with this format for each file:

### filename.py

**Status:** PASS/FAIL/SKIP

**Description:** What the test does.

**Result:** Summary of output or error.

---
