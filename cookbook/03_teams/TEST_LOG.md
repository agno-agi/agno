# TEST_LOG - 03_teams

**Test Date:** 2026-01-16
**Environment:** `.venvs/demo/bin/python`
**Branch:** `v2.4-with-cookbooks`

---

## basic_flows/

### 01_basic_coordination.py

**Status:** SKIPPED (Missing dependency)

**Description:** Requires `newspaper4k` module which is not installed.

---

### 02_respond_directly_router_team.py

**Status:** PASS

**Description:** Language router team. Correctly routed requests to appropriate language agents and responded in English when asked in unsupported language (Italian: "Come stai?") with appropriate fallback message listing supported languages.

---

## state/

### pass_state_to_members.py

**Status:** PASS

**Description:** Shared state passing to team members. Team correctly accessed session state `{'user_name': 'John', 'age': 30}` and responded accurately with "You're 30 years old, John."

---

## streaming/

### 01_team_streaming.py

**Status:** PASS

**Description:** Team streaming response. Team delegated task to Stock Searcher member, streamed response events correctly. Demonstrated proper task delegation flow with `delegate_task_to_member`.

---

## structured_input_output/

### 00_pydantic_model_output.py

**Status:** PASS

**Description:** Pydantic model output for teams. Stock Searcher team returned properly structured JSON output with symbol, company_name, and analysis fields for NVDA query.

---

## Summary

| Folder | Test | Status |
|:-------|:-----|:-------|
| basic_flows/ | 01_basic_coordination.py | SKIPPED (newspaper4k) |
| basic_flows/ | 02_respond_directly_router_team.py | PASS |
| state/ | pass_state_to_members.py | PASS |
| streaming/ | 01_team_streaming.py | PASS |
| structured_input_output/ | 00_pydantic_model_output.py | PASS |

**Total:** 4 PASS, 1 SKIPPED

**Notes:**
- 117 total files in folder - sample tested for coverage
- Some basic_flows examples require newspaper4k dependency
- Team model inheritance and task delegation working correctly
- Streaming and structured output features functional
