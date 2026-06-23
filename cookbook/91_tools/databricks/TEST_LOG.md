# TEST_LOG

### jobs.py

**Status:** PASS

**Description:** Re-ran the Databricks Jobs inspection cookbook after gating run/cancel operations behind explicit admin enablement and listed live jobs with the default read-only toolkit.

**Result:** Returned the live job list successfully, including the configured `DATABRICKS_JOB_ID`. The default toolkit path remained read-only and no admin operations were mounted.

---

### jobs_admin.py

**Status:** PASS

**Description:** Ran the Databricks Jobs admin cookbook to verify explicit admin-tool enablement and confirmation-gated operation exposure without mutating workspace state.

**Result:** Printed the admin functions and confirmed that the admin toolkit requires explicit `enable_admin_tools=True` plus an admin credential path. The cookbook was validated with an explicitly supplied `DATABRICKS_ADMIN_TOKEN`.

---

### sql.py

**Status:** PASS

**Description:** Ran the Databricks SQL cookbook against the configured SQL warehouse and listed tables from the configured catalog and schema.

**Result:** Returned the live `samples.bakehouse` tables successfully. The Databricks SQL connector emitted its expected `pyarrow` optional dependency warning, but the cookbook completed correctly.

---

### unity_catalog.py

**Status:** PASS

**Description:** Ran the Databricks Unity Catalog cookbook against the configured workspace and listed visible catalogs.

**Result:** Returned live catalog metadata including `system`, `samples`, and `workspace`.

---

### vector_search.py

**Status:** PASS

**Description:** Re-ran the Databricks Vector Search cookbook after gating create/sync/upsert/delete operations behind explicit admin enablement and queried the live inspection path against endpoint `agno-experiment` and index `workspace.default.media_gold_reviews_chunked_idx`.

**Result:** Listed the live vector search endpoint and described the configured delta-sync index successfully, including source table, primary key, embedding source column, and indexed row count. The default toolkit path remained inspection-only and no admin operations were mounted.

---

### workspace.py

**Status:** PASS

**Description:** Re-ran the Databricks workspace cookbook after gating create/import/delete operations behind explicit admin enablement and listed objects under the workspace root path.

**Result:** Returned live workspace directories including `/Users`, `/Shared`, and `/Repos`. The default toolkit path remained inspection-only and no admin operations were mounted.

---
