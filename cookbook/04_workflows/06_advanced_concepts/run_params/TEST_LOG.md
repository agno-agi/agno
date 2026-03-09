# TEST_LOG for cookbook/04_workflows/06_advanced_concepts/run_params

Generated: 2026-03-09

### workflow_metadata.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal). Tests metadata propagation from workflow to agents.

**Result:** Both examples completed successfully. Example 1 showed class-level metadata (project=acme, tier=production). Example 2 showed merged metadata with class-level winning on conflicts (project=acme, not override-attempt) and call-site keys preserved (experiment=v2).

---

### workflow_dependencies.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal). Tests dependency injection through workflows with add_dependencies_to_context.

**Result:** Both examples completed successfully. Example 1 showed workflow-level dependencies (database_url, api_version=v2). Example 2 showed merged dependencies with call-site winning on conflicts (api_version=v3) and new keys added (feature_flag=new_ui).

---

### workflow_context_flags.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal). Tests context control flags (add_dependencies_to_context, add_session_state_to_context, debug_mode) at workflow level.

**Result:** All three examples completed successfully. Example 1 propagated dependencies and session state to both agents. Example 2 enabled debug_mode from call-site. Example 3 ran async with add_dependencies_to_context overridden to False.

---

### workflow_all_params.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` (mode: normal). Tests all run-level params together in a content creation pipeline.

**Result:** All three examples completed successfully. Example 1 used workflow defaults (tone=professional, audience=developers). Example 2 overrode dependencies at call-site (tone=casual, audience=beginners) with merged metadata. Example 3 ran async with debug_mode=True.

---
