# Test Log — 04_tools

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| 01_callable_tools.py | PASS | Role-based callable tools (user/admin), web search and internal doc tools |
| 02_session_state_tools.py | PASS | Factory-resolved greet/farewell modes with session state tools |
| 03_team_callable_members.py | PASS | Team with researcher+writer callable members, produces Python history summary |
| tool_call_limit.py | PASS | Tool call limit enforced, stock price retrieved but news hit limit (expected behavior) |
| tool_choice.py | PASS | Tool choice forces get_weather, first call uses "none" (no tool), second forces tool call |
