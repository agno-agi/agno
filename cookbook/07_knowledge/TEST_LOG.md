# TEST_LOG

## 07_knowledge

No tests recorded yet.

---

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Validated restructured knowledge cookbooks by running the checker across merged quickstart, embedders, and all vector_db backend subdirectories.

**Result:** All checked directories reported 0 violations after restructuring.

---

### 05_integrations/vector_dbs/05_opengauss_datavec.py (2026-04-15 rerun)

**Status:** PASS

**Description:** Re-ran the cookbook end-to-end in the project virtual environment with DashScope embedding and model endpoints. Verified both basic vector search and hybrid search flows against local openGauss.

**Result:** `source .venv/bin/activate && python cookbook/07_knowledge/05_integrations/vector_dbs/05_opengauss_datavec.py` completed successfully (exit code 0). Both prompts returned grounded cookbook answers. Only a non-blocking SQLAlchemy statement-cache warning was observed.

---
