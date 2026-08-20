# Test Log

Tested 2026-08-20 against `gpt-5.5` (OpenAIResponses), SQLite, with the worktree's Python (agno from this branch). `Team(offload_tool_results=ResultStore(threshold_chars=8000))`.

### offload_member_results.py

**Status:** PASS

**Description:** A leader with a platform builder, manager and engineer. Two turns: a deployment log question, then a component inventory question. Both member tools return large payloads (a 1,500-line log of 69,861 bytes and a 1,200-line inventory of 51,499 bytes).

**Result:** Both answers are correct: event 01180 failed with `ERROR connection refused`, and team-3 owns 134 components. Two results were stored for the session, one per member tool call, and 121,360 bytes of tool payload stayed out of the leader's transcript. The leader's whole transcript was 2,564 characters after turn one and 4,556 after turn two. The members' own answers were short enough to stay inline under the 8,000-character threshold; with a lower threshold they are stored as well, once as the delegation result and once as the member's stored run (the duplication the README describes). The members and the leader read back through `read_result` and `search_result` without any instruction beyond the line the framework adds. No warnings, no traceback.

---

### handing_a_result_to_a_member.py

**Status:** PASS

**Description:** The leader asks the platform engineer to pull incident INC-4417. The tool returns a 1,201-line, 79.7KB report, which is offloaded before the engineer ever sees it. The engineer hands back the result id. The leader then puts that id in the task for the platform manager, and the manager reads it through the store it shares with the leader.

**Result:** The leader's second delegation named `res_da944b1e1f` rather than the text. The manager searched and read that id and answered: finding 00640, severity critical, service api-2, timeout after 10s. That matches the generated data (640 mod 11 = 2, 640 mod 90 = 10). The report text crossed the team once, as a file. No warnings, no traceback.

---
