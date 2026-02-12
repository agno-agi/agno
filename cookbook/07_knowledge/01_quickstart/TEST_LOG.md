# TEST_LOG

## 01_quickstart — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### 01_from_path.py

**Status:** PASS

**Description:** Loads PDF CVs from local path into PgVector, queries agent about candidate skills. Tests sync/async insert and agent search.

**Result:** Successfully loaded PDFs, agent correctly identified Jordan Mitchell's skills (JavaScript, React, Python, HTML/CSS, Git).

---

### 02_from_url.py

**Status:** PASS

**Description:** Loads Thai recipes PDF from S3 URL into PgVector, queries agent about recipes.

**Result:** Successfully downloaded, chunked (14 docs), and searched. Agent returned detailed Thai recipe information. Cleanup (remove_vectors_by_name) worked.

---

### 03_from_topic.py

**Status:** FAIL

**Description:** Loads knowledge from Wikipedia and Arxiv topics using WikipediaReader and ArxivReader.

**Result:** ImportError — `arxiv` package not installed in demo venv. Not a v2.5 regression, dependency issue.

---

### 04_from_multiple.py

**Status:** PASS

**Description:** Loads from mixed sources (local paths + S3 URLs) with custom embedder and metadata. Tests insert_many with dict and keyword variants.

**Result:** Successfully inserted multiple sources with metadata. Both sync and async knowledge bases populated correctly.

---

### 05_from_youtube.py

**Status:** PASS

**Description:** Loads knowledge from YouTube video transcript, queries agent about Thai recipes.

**Result:** Successfully extracted YouTube transcript, chunked (14 docs), and searched. Agent returned detailed Thai recipe answers.

---

### 06_from_s3.py

**Status:** SKIP

**Description:** Loads knowledge from AWS S3 via S3Content remote content wrapper.

**Result:** Skipped — requires AWS credentials and agno-aws package for S3 access.

---

### 07_from_gcs.py

**Status:** SKIP

**Description:** Loads knowledge from Google Cloud Storage via GCSContent remote content wrapper.

**Result:** Skipped — requires GCP credentials and google-cloud-storage package.

---

### 08_include_exclude_files.py

**Status:** PASS

**Description:** Loads directory with include/exclude glob filters (*.pdf, exclude *cv_5*). Tests agent query on filtered knowledge.

**Result:** Successfully filtered files during insert. Agent correctly noted Alex Rivera info was not found (excluded file). Include/exclude patterns work correctly.

---

### 09_remove_content.py

**Status:** PASS

**Description:** Tests content lifecycle: insert, list (get_content), remove by ID (remove_content_by_id), and remove all (remove_all_content). Both sync and async.

**Result:** All CRUD operations worked. Content IDs printed, individual and bulk deletion succeeded.

---

### 10_remove_vectors.py

**Status:** PASS

**Description:** Tests vector removal by metadata (remove_vectors_by_metadata) and by name (remove_vectors_by_name). Both sync and async.

**Result:** Successfully removed vectors by metadata tag and by name. Re-insertion after removal worked correctly.

---

### 11_skip_if_exists.py

**Status:** PASS

**Description:** Tests idempotent insertion with skip_if_exists flag. First insert with skip=True, then with skip=False to force re-insert.

**Result:** skip_if_exists=True correctly skipped existing content. skip_if_exists=False re-inserted (upserted) content.

---

### 12_skip_if_exists_contentsdb.py

**Status:** PASS

**Description:** Tests migrating existing vectors to contents DB by dynamically assigning contents_db after initial insert.

**Result:** Initial insert without contents_db worked. Re-insert with contents_db populated content tracking. Skip behavior correct after migration.

---

### 13_specify_reader.py

**Status:** PASS

**Description:** Explicitly specifies PDFReader for file loading instead of relying on auto-detection. Tests agent query.

**Result:** PDFReader correctly used. Agent answered "What documents are in the knowledge base?" with knowledge base content overview.

---

### 14_text_content.py

**Status:** PASS

**Description:** Tests direct text insertion via text_content parameter and insert_many with text_contents. Both sync and async.

**Result:** All 3 insertion styles worked (single text, multiple texts, dict format). Minor warnings about content rows not found when contents_db not configured — expected behavior.

---

### 15_batching.py

**Status:** FAIL

**Description:** Tests batch embeddings with OpenAI embedder using LanceDb vector store.

**Result:** ImportError — `lancedb` package not installed in demo venv. Not a v2.5 regression, dependency issue.

---

### 16_knowledge_instructions.py

**Status:** PASS

**Description:** Tests Agent with add_search_knowledge_instructions=False to disable automatic search instructions in system prompt.

**Result:** Agent successfully loaded Thai recipes from URL and answered queries without search instructions in prompt.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 12    | 01, 02, 04, 05, 08, 09, 10, 11, 12, 13, 14, 16 |
| FAIL   | 2     | 03 (arxiv pkg), 15 (lancedb pkg) |
| SKIP   | 2     | 06 (S3 creds), 07 (GCS creds) |

No v2.5 regressions detected. All failures are dependency issues (missing packages in demo venv).
