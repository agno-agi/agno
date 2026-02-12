# Review Log: human_in_the_loop

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] `NameError: name 'requirements' is not defined` — All HITL cookbooks log `WARNING Error upserting session into db: name 'requirements' is not defined` during session persistence. This comes from `agno/db/sqlite/sqlite.py` in the `upsert_session` method. The session IS persisted (continue_run works), but the warning indicates a variable reference bug in the serialization path. Observed in prior test runs (2026-02-08 logs), still present.

## Cookbook Quality

[QUALITY] All 12 cookbooks — Excellent comprehensive coverage of HITL patterns. Three interaction types (confirmation, external_execution, user_input) × four variants (sync, async, stream, async_stream) plus rejection and team-level tools. Each file is standalone and well-documented.

[QUALITY] confirmation_required.py — Uses `rich.prompt.Prompt.ask` for interactive input. Good demo of the full interactive flow with session persistence (`SqliteDb`). The `active_requirements` property correctly filters to actionable requirements.

[QUALITY] user_input_required.py — Vague prompt "Help me plan a vacation" does not reliably trigger `plan_trip` tool call. Model (gpt-4o-mini) consistently responds conversationally instead. The streaming variant (`user_input_required_stream.py`) uses more specific "Book a flight to Tokyo for next Friday" which works reliably. Consider updating the sync version's prompt to be more directive.

[QUALITY] external_tool_execution_stream.py — Interesting pattern: calls `run_shell_command.entrypoint(**req.tool_execution.tool_args)` to actually execute the tool externally. The `.entrypoint` attribute is the unwrapped function on `@tool`-decorated callables. Good for demos showing external execution as "run it yourself, give us the result".

[QUALITY] team_tool_confirmation.py vs member confirmation — Good contrast. Team-level tools pause the team leader directly (no member agent involved). Member-level tools pause the member, which propagates up to the team. Both patterns are demonstrated clearly.

[QUALITY] confirmation_required_async_stream.py — Note: `team.acontinue_run()` is called without `await` on line 63, but the result is passed to `await pprint.apprint_run_response(response)` which handles the async iteration. This works because `acontinue_run` with `stream=True` returns an async generator, and `apprint_run_response` iterates it. Might confuse readers expecting an `await` call.

## Fixes Applied

(none needed — all cookbooks use correct v2.5 patterns)
