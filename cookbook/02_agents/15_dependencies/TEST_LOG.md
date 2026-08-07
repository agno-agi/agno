# Test Log -- 15_dependencies

**Tested:** 2026-04-28
**Environment:** .venvs/demo/bin/python (gpt-5.4)

---

### 01_static_dependencies.py

**Status:** PASS
**Description:** Plain dict values as dependencies; verified the agent receives feature flags and tenant config in context.
**Result:** Completed successfully in ~3s.

---

### 02_callable_dependencies.py

**Status:** PASS
**Description:** Sync callables resolved once per run; current_time and active_users injected.
**Result:** Completed successfully in ~3s.

---

### 03_async_dependencies.py

**Status:** PASS
**Description:** Async dependency resolvers awaited via `aprint_response`.
**Result:** Completed successfully in ~3s.

---

### 04_template_strings_in_instructions.py

**Status:** PASS
**Description:** `{user_profile}` and `{tone}` substituted into instructions; agent matched stated tone.
**Result:** Completed successfully in ~9s.

---

### 05_run_level_overrides.py

**Status:** PASS
**Description:** Class-level defaults override-able per-run; second run shows different tone and added audience key.
**Result:** Completed successfully in ~6s.

---

### 06_runtime_aware_dependencies.py

**Status:** PASS
**Description:** Resolvers read `run_context.user_id` and `agent.name`; profile differs by user.
**Result:** Completed successfully in ~4s.

---

### 07_dependencies_with_memory.py

**Status:** PASS
**Description:** Combined dependencies (per-run profile) with persistent user memory across two sessions.
**Result:** Completed successfully in ~10s.

---

### dependencies_in_context.py

**Status:** PASS
**Description:** Demonstrates dependencies in context (HackerNews summary).
**Result:** Ran successfully after gpt-5.4 model update.

---

### dependencies_in_tools.py

**Status:** PASS
**Description:** Demonstrates dependencies accessed inside a tool via `run_context.dependencies`.
**Result:** Ran successfully after gpt-5.4 model update.

---

### dynamic_tools.py

**Status:** PASS
**Description:** Demonstrates a callable tools factory (note: this is a tools example placed here for now).
**Result:** Ran successfully after gpt-5.4 model update.

---
