# Test Log

Tested 2026-08-20 against `gpt-5.5` (OpenAIResponses), SQLite, with the worktree's Python (agno from this branch). `Team(offload_tool_results=ResultStore(threshold_chars=8000))`.

### offload_member_results.py

**Status:** PASS (re-tested 2026-08-21 against `gpt-5.5`, SQLite)

**Description:** A leader with three members over two turns: the engineer reads a 1,500-line deployment log, then the builder answers with the full component inventory. `ResultStore(threshold_chars=1500)` so both sides of the threshold show in one run, and `store_member_responses=True` so the last line can print what the caller reads.

**Result:** Two consecutive runs behaved identically. Turn one: the engineer's short answer stayed inline in the leader's transcript (353 and 335 characters across the two runs) while its own 69,861-byte tool result was stored. Turn two: the builder's inventory answer crossed the threshold and reached the leader as a 1,053-character envelope, and the leader read it back with `read_result` / `search_result`; the same answer measured 5,745 and 6,656 characters through `RunOutput.member_responses`, so offloading changed what the model read and not what the caller reads. Four results were stored per run (the two members' tool results at 51,499 and 69,861 bytes, the member answer as the delegation result, and the member's own stored run). Answers were correct both times (failing event 01180 on worker-4; team-3 component count). No warnings, no traceback.


### handing_a_result_to_a_member.py

**Status:** PASS

**Description:** The leader asks the platform engineer to pull incident INC-4417. The tool returns a 1,201-line, 79.7KB report, which is offloaded before the engineer ever sees it. The engineer hands back the result id. The leader then puts that id in the task for the platform manager, and the manager reads it through the store it shares with the leader.

**Result:** The leader's second delegation named `res_da944b1e1f` rather than the text. The manager searched and read that id and answered: finding 00640, severity critical, service api-2, timeout after 10s. That matches the generated data (640 mod 11 = 2, 640 mod 90 = 10). The report text crossed the team once, as a file. No warnings, no traceback.

---

### member_store_settings.py

**Status:** PASS (tested 2026-08-21 against `gpt-5.5`, SQLite)

**Description:** A team with `offload_tool_results=ResultStore(threshold_chars=8000)` and three members: one with the setting unset, one with `offload_tool_results=False`, one with its own `ResultStore(threshold_chars=4000, preview_lines=2, preview_chars=120)`. Each reads a 50,279-character metrics dump for its service. After the run the example prints each member's store and what its stored history holds.

**Result:** The leader delegated once per member and reported 5 errors for each service (verified: one error sample per 211 in 1,200). The inheriting member showed the team's store (threshold 8000, preview_lines 20); the opted-out member showed no store; the own-settings member showed its own settings bound to the team db (threshold 4000, preview_lines 2). In the stored session the inheriting member's tool result was a 961-character envelope, the opted-out member's was the full 50,279-character text, and the own-settings member's was a 278-character envelope with its two-line preview. No warnings, no traceback.

---
