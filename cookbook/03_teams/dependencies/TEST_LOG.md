# Test Log: dependencies

> Updated: 2026-02-11

### dependencies_in_context.py

**Status:** PASS

**Description:** Demonstrates team-level `dependencies` dict with callable factories (`get_user_profile`, `get_current_context`) and `add_dependencies_to_context=True` for template-based injection into team instructions.

**Result:** Completed successfully in ~58s. Dependencies resolved at runtime and injected into instruction templates via `{user_profile}` and `{current_context}` placeholders. Team produced personalized workday priorities.

---

### dependencies_in_tools.py

**Status:** PASS

**Description:** Demonstrates two patterns: (1) runtime `add_dependencies_to_context=True` via `team.run()` kwargs, and (2) accessing dependencies inside team tools via `run_context.dependencies`. Uses both callable factories and raw dict values.

**Result:** Both patterns completed successfully in ~58s. Personalization team used context dependencies for instruction templates. Performance team accessed `team_metrics` and `current_context` through `RunContext.dependencies` in the `analyze_team_performance` tool.

---

### dependencies_to_members.py

**Status:** PASS

**Description:** Demonstrates passing dependencies via `team.print_response()` kwargs with `add_dependencies_to_context=True` and `show_members_responses=True`. Dependencies propagate to member agents (ProfileAnalyst, ContextAnalyst).

**Result:** Completed successfully in ~55s. Dependencies passed at call time were propagated to member agents. Both members produced responses informed by the injected user profile and context data.

---
