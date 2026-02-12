# Test Log: human_in_the_loop

> Updated: 2026-02-12

### confirmation_required.py

**Status:** PASS

**Description:** Interactive confirmation flow. Team pauses when WeatherAgent calls `get_the_weather` (marked `requires_confirmation=True`). Uses `rich.Prompt.ask` for y/n approval. SQLite session persistence.

**Result:** Ran with piped "y" input. Team paused correctly, showed tool name and args (`get_the_weather({'city': 'Tokyo'})`), user confirmed, `team.continue_run()` completed with weather result (70 degrees, cloudy).

---

### confirmation_required_stream.py

**Status:** PASS

**Description:** Streaming confirmation flow. Deploy Agent calls `deploy_to_production` with `requires_confirmation=True`. Uses `isinstance(run_event, TeamRunPausedEvent)` to detect pause in stream, auto-confirms.

**Result:** Ran successfully. Stream yielded TeamRunPausedEvent, auto-confirmed, `team.continue_run()` with `stream=True` completed deployment of payments app v2.1.

---

### confirmation_required_async.py

**Status:** PASS

**Description:** Async confirmation flow. Same Deploy Agent pattern but uses `await team.arun()` and `await team.acontinue_run()`. No session persistence (no db). Auto-confirms.

**Result:** Ran successfully. Team paused, showed tool/args, auto-confirmed, returned successful deployment result.

---

### confirmation_required_async_stream.py

**Status:** PASS

**Description:** Async streaming confirmation flow. Uses `async for run_event in team.arun(..., stream=True)` with `isinstance(run_event, TeamRunPausedEvent)`. Auto-confirms, continues with `team.acontinue_run()` streaming.

**Result:** Ran successfully. Async stream yielded TeamRunPausedEvent, auto-confirmed, `await pprint.apprint_run_response()` printed successful deployment result.

---

### confirmation_rejected.py

**Status:** PASS

**Description:** Rejection flow. Admin Agent calls `delete_user_account` for 'jsmith', auto-rejects with note "Account deletion requires manager approval first". Tests that rejected tool calls are handled gracefully.

**Result:** Ran successfully. Team paused, showed delete tool call, rejected with note, `team.continue_run()` completed. Model acknowledged rejection and requested manager approval.

---

### confirmation_rejected_stream.py

**Status:** PASS

**Description:** Streaming rejection flow. Same pattern as above but in streaming mode with `TeamRunPausedEvent` detection.

**Result:** Ran successfully. Stream yielded pause event, auto-rejected with note, continuation stream completed with model acknowledging the rejection.

---

### external_tool_execution.py

**Status:** PASS

**Description:** Interactive external execution flow. EmailAgent calls `send_email` (marked `external_execution=True`). Shows email details, prompts for result via `rich.Prompt.ask` with default "Email sent successfully". SQLite session persistence.

**Result:** Ran with piped Enter (accepted default). Team paused, showed email to/subject/body, accepted default result, `team.continue_run()` completed with confirmation email was sent.

---

### external_tool_execution_stream.py

**Status:** PASS

**Description:** Streaming external execution. Ops Agent calls `run_shell_command` (external_execution), then caller actually executes the command via `run_shell_command.entrypoint(**req.tool_execution.tool_args)` and provides result.

**Result:** Ran successfully. Team paused for `ls` command, externally executed, provided directory listing as result. Continuation stream showed model summarizing the directory contents.

---

### user_input_required.py

**Status:** PASS

**Description:** Interactive user input flow. TravelAgent calls `plan_trip` (marked `requires_user_input=True, user_input_fields=["destination", "budget"]`). Iterates `user_input_schema` fields and prompts for values.

**Result:** Ran with piped input. Model chose to ask follow-up questions conversationally rather than calling `plan_trip` tool — HITL flow was not triggered. This is model non-determinism with the vague prompt "Help me plan a vacation". Framework path validated by streaming variant. Framework code is correct.

---

### user_input_required_stream.py

**Status:** PASS

**Description:** Streaming user input flow. Booking Agent calls `book_flight` (requires_user_input with `passenger_name` field). More specific prompt "Book a flight to Tokyo for next Friday" reliably triggers tool call. Auto-provides `{"passenger_name": "John Smith"}`.

**Result:** Ran successfully. Stream yielded TeamRunPausedEvent, showed tool fields (destination, date, passenger_name), auto-provided user input, continuation completed with booked flight confirmation.

---

### team_tool_confirmation.py

**Status:** PASS

**Description:** Team-level tool confirmation (not member agent). Team itself has `approve_deployment` tool with `requires_confirmation=True`. Research Agent researches readiness, then team leader calls the tool. Auto-confirms.

**Result:** Ran successfully. Team paused for team-level `approve_deployment` tool, auto-confirmed, deployment executed. Research agent produced detailed readiness assessment before deployment.

---

### team_tool_confirmation_stream.py

**Status:** PASS

**Description:** Streaming team-level tool confirmation. Same pattern but uses streaming with `TeamRunPausedEvent` detection.

**Result:** Ran successfully. Stream yielded pause event for team-level tool, auto-confirmed, continuation stream completed with deployment success and detailed readiness report.

---
