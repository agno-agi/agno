# Test log

Run with the worktree `.venv` (agno installed from this branch), `gpt-5.5` through `OpenAIResponses`, SQLite.

### handing_a_result_to_a_member.py

**Status:** PASS

**Description:** The leader asks the platform engineer to pull incident INC-4417. The tool returns a 1201 line report, which is offloaded before the engineer ever sees it. The engineer hands back the result id. The leader then puts that id in the task for the platform manager, and the manager reads it through the store it shares with the leader.

**Result:** The leader's second delegation read `read the full incident report ... from stored result id res_a8bcaec7c0`. The manager read that id and answered: finding 00640, critical, service api-2, timeout after 10s. That matches the generated data exactly (640 mod 11 = 2, 640 mod 90 = 10). The report text crossed the team once, as a file.

---

### offload_member_results.py

**Status:** PASS

**Description:** A leader with a platform builder, manager and engineer. Two turns: a deployment log question, then a component inventory question. Both member tools return large payloads.

**Result:** Four results were stored for the session:

```
res_52a14a6466 from assistant_message           65 lines,  2,980 bytes
res_915b07fa08 from delegate_task_to_member     65 lines,  2,980 bytes
res_3de7befea8 from list_platform_components  1200 lines, 51,499 bytes
res_a0454d8074 from read_deployment_log       1500 lines, 69,861 bytes
```

121KB of tool payload stayed out of the leader's messages, and the member's own report was offloaded on both sides: as the delegation result the leader reads, and as the member's own stored assistant message. The leader's whole transcript for the second turn was 6,354 characters, of which the delegation result was 790. The leader called `read_result` on its own before answering, which is the intended loop. The answer, 134 components owned by team-3, is correct.

The two 2,980 byte rows are the same answer stored twice, once per surface. That is the known duplication noted in the README.

---
