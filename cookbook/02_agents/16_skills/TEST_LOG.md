# Test Log -- 16_skills

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### basic_skills.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates basic skills. Ran successfully and produced expected output.
**Result:** Completed successfully in 8s.

---

## 2026-08-04: Database-backed skills

**Tested:** 2026-08-04
**Environment:** .venvs/demo/bin/python (no API key needed; the model is never invoked)

### db_skills.py

**Status:** PASS
**Tier:** untagged
**Description:** Creates a content-carrying skill in the SQLite skills table, attaches it to an agent through DbSkills, saves the agent, loads it back, and executes the skill script directly through the get_skill_script tool entrypoint.
**Result:** Ran twice back to back. Both runs resolved the skill from the database after load (source_type db, content matching the stored row) and the script executed from database content, printing {'kilometers': 5.0, 'miles': 3.107}.

---
