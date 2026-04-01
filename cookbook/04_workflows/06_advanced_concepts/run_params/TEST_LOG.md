# TEST_LOG for cookbook/04_workflows/06_advanced_concepts/run_params

Generated: 2026-03-10

### workflow_dependencies.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal). Tests dependency injection through workflows with add_dependencies_to_context.

**Result:** Both examples completed successfully. Example 1 showed workflow-level dependencies (database_url, api_version=v2). Example 2 showed merged dependencies with call-site winning on conflicts (api_version=v3) and new keys added (feature_flag=new_ui).

---

### workflow_all_params.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal). Tests all run-level params together in a content creation pipeline.

**Result:** All three examples completed successfully. Example 1 used workflow defaults (tone=professional, audience=developers). Example 2 overrode dependencies at call-site (tone=casual, audience=beginners) with merged metadata. Example 3 ran async.

---
