# Test Log — 01_quickstart

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| 01_from_path.py | PASS | Loaded CV from local PDF, agent answered skill query correctly |
| 02_from_url.py | PASS | Loaded Thai recipes from S3 URL, agent answered recipe questions |
| 03_from_topic.py | PASS | Loaded Wikipedia topics (Manchester United, Carbon Dioxide, Nitrogen) |
| 04_from_multiple.py | PASS | Loaded from path + URL + topic combined knowledge sources |
| 05_from_youtube.py | PASS | Loaded YouTube transcript, agent answered about building agents |
| 06_from_s3.py | PASS | Loaded Thai recipes directly from S3, agent provided recipe details |
| 07_from_gcs.py | SKIP | Missing: GCS credentials (RefreshError: Reauthentication needed) |
| 08_include_exclude_files.py | PASS | Include/exclude file filtering worked correctly |
| 09_remove_content.py | PASS | Content removal by ID, hash, name, and metadata all worked |
| 10_remove_vectors.py | PASS | Vector removal by name and metadata worked |
| 11_skip_if_exists.py | PASS | Skip-if-exists deduplication logic ran correctly |
| 12_skip_if_exists_contentsdb.py | PASS | Content DB-based skip-if-exists ran correctly |
| 13_specify_reader.py | PASS | Specified reader for URL content, agent queried knowledge base |
| 14_text_content.py | PASS | Raw text content ingestion and querying worked |
| 15_batching.py | PASS | Batch loading of multiple documents ran correctly |
| 16_knowledge_instructions.py | PASS | Knowledge instructions with agent, returned Thai recipe details |
| 17_isolate_vector_search.py | PASS | Isolated vector search (no agent), returned correct results |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 16    |
| SKIP   | 1     |

SKIP: 07_from_gcs.py (GCS credentials not available)
