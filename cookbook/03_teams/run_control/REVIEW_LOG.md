# Review Log: run_control

> Updated: 2026-02-11

## Framework Issues

[FRAMEWORK] team/team.py — Default model assignment: when no model is set on Team, it defaults to `OpenAIChat(id="gpt-4o")`. This is implicit and not documented in the cookbook. Log message "Setting default model to OpenAI Chat" appears but doesn't specify which model ID.

[FRAMEWORK] team/_run.py — Cancel timing issue: `cancel_run()` returns True but if the run completes before the cancellation propagates, the final status remains "completed" not "cancelled". The cancel_run.py cookbook demonstrates this race condition.

## Cookbook Quality

[QUALITY] retries.py — Team has no explicit `model=` parameter, relying on the framework's default model (gpt-4o). This works but is not transparent to learners. Should add `model=OpenAIChat("gpt-4o")` explicitly.

[QUALITY] cancel_run.py — Good demonstration of threading + cancellation, but the 8-second delay is often too long for o3-mini which completes fast. May want to use a slower model or longer prompt to reliably demonstrate cancellation mid-flight.

[QUALITY] remote_team.py — Clean example of RemoteTeam. Properly shows both arun() and streaming variants. Requires AgentOS which limits testability.

## Fixes Applied

(none needed)
