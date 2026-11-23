# Test log: harness agents as team members

### claude_member.py

**Status:** PASS (claude-sonnet-4-6 member, gpt-5.6-luna leader and writer)

**Description:** A team with a Claude Code engineer and an Agno writer, on a temporary copy of the sample project. Turn 1 asks for a pytest test for the 100 dollar boundary to be written, run and summarised; turn 2, on the same session, asks the engineer which file it created and what it asserts.

**Result:** Turn 1: Claude created `test_shipping.py`, ran it (all tests passed) and the writer summarised. Turn 2: the leader delegated to the engineer, which answered from its own resumed conversation with the file name and the boundary assertions. The workspace held `shipping.py` and `test_shipping.py` afterwards.

---

### codex_member.py

**Status:** PASS (gpt-5.6-luna leader and Codex)

**Description:** A team with a read-only Codex reviewer. Turn 1 asks for at most three issues in `shipping.py`; turn 2, on the same session, asks the reviewer which point matters most for the 100 dollar boundary.

**Result:** Turn 1: Codex reported that booleans and NaN pass the int-annotated input unchecked. Turn 2 was answered by `codex-reviewer`, continuing its thread: NaN matters most because both comparisons are false, so it bypasses the threshold and is charged 8 dollars. The member's own session `shipping-code-review:codex-reviewer` held the Codex thread id next to the team's session. A first run without `add_history_to_context=True` on the team had the leader answer the follow-up itself, which is why the cookbook turns it on.

---

### mixed_team.py

**Status:** PASS (claude-sonnet-4-6, Codex on gpt-5.6-luna, gpt-5.6-luna leader and writer)

**Description:** Claude Code, Codex and an Agno agent in one team, asked to add tests for the 100 dollar boundary and a negative subtotal.

**Result:** The leader delegated in order: `claude-engineer` created `test_shipping.py` and ran it (4 passed, `shipping.py` unchanged), `codex-reviewer` approved the coverage with a minor documentation note, and `writer` summarised both. All three member runs were COMPLETED and recorded on the team run.

---

### team_agentos.py

**Status:** PASS

**Description:** A self-contained team of Claude Code, Codex and an Agno writer served through AgentOS (on the port from `AGENT_OS_PORT`, 7778 in the test environment). Read `GET /teams/mixed-team`, then streamed one run with `POST /teams/mixed-team/runs` asking only the Codex Reviewer whether `shipping.py` rejects negative subtotals.

**Result:** The team response listed `claude-engineer` (sdk `claude-agent-sdk`), `codex-reviewer` (sdk `codex`) and `writer`. The streamed run delegated only to `codex-reviewer`, whose events reached the client, and ended with `TeamRunCompleted`. An earlier version imported the team from `mixed_team.py`, whose fixed order made the leader delegate to all three members; this one defines its own team and instructs the leader to involve only the members a request needs.

Re-run with the agents also served directly (`AgentOS(agents=[engineer, reviewer, writer], teams=[team])`), so AgentOS and the team share one Claude Engineer instance. A team run on session `team-s1` delegated to `claude-engineer` and completed. Afterwards, a non-streaming and a streaming `POST /agents/claude-engineer/runs` on sessions `solo-1` and `solo-2` both completed, and `GET /sessions/{id}/runs` returned each run. The database held the standalone runs in their own agent sessions with no team metadata, the member's state session `team-s1:claude-engineer` with `team_id` `mixed-team`, and no `solo-1:claude-engineer` row.

---

### sandboxed_member.py

**Status:** PASS (claude-sonnet-4-6 member in `agno-sandbox:local`, gpt-5.6-luna leader, Postgres)

**Description:** A team whose engineer is Claude Code in a `DockerSandbox`. Turn 1 asks for `fizzbuzz.py` for 1 to 15 to be written and run; turn 2, on the same session, asks the engineer to change it to go up to 20 and run it again.

**Result:** Turn 1: Claude wrote and ran `fizzbuzz.py` in its container; last line `FizzBuzz`. Turn 2: the leader delegated again and Claude edited the existing `/workspace/fizzbuzz.py` (replacing `range(1, 16)`), ran it and reported `Buzz`. The file and the conversation carried over on the member's own computer.

---

### sandboxed_team_agentos.py

**Status:** PASS

**Description:** The sandboxed team served through AgentOS with `QueueConfig(durable=True, db=db)` on Postgres and no member database of its own. Submitted a background team run with `POST /teams/sandboxed-team/runs`, polled it, and read `GET /teams/sandboxed-team`.

**Result:** The queued run completed; its member response was `sandboxed-engineer` COMPLETED, having written and run `fizzbuzz.py` (last line `FizzBuzz`). The team response listed `sandboxed-engineer` with `sandboxed: true`. AgentOS gave the member the OS database at startup.

---

### Unit and integration tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/team/test_external_agent_members.py` (14): a scripted leader delegating to Claude members on a fake SDK and to a Codex member on a fake SDK; covers member runs in the team session, the member's own state session, resume, two members, streaming, Codex threads, message input, AgentOS listing, native-only settings, the member-run storage paths, and the sandboxed member's forwarded options and reporting. `libs/agno/tests/integration/sandbox/test_team_members.py` (4), on Docker and Postgres with the fixture runtime: two team turns on one sandboxed member whose second checkpoint holds both turns, with the team's records in the team session and the sandbox's in the member session; two sandboxed members each on their own computer; a streamed team run carrying the member's events on the team session; cancelling the team run mid-turn ending the sandbox's own run cancelled and the next turn running. `test_sandbox_param.py`: AgentOS applies the sandbox startup checks to team members at any depth.

**Result:** All pass. The agents, team and sandbox unit suites: 1976 passed. AgentOS team and sandbox unit tests: 239 passed. Sandbox integration (`test_team_members.py`, `test_agentos.py`, `test_coordinator.py`): 148 passed, 11 skipped (opt-in cases).

---
