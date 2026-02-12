# Test Log — 09_hooks

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| post_hook_output.py | PASS | Post-hook validates output length and quality, blocks short/empty and passes normal |
| pre_hook_input.py | PASS | Pre-hook validates financial advisor input, blocks vague/off-topic/unsafe content |
| session_state_hooks.py | PASS | Session state hooks track topics across runs, state persists |
| stream_hook.py | PASS | Stream hook logs tool calls with timing, Apple stock analysis streamed |
| tool_hooks.py | PASS | Tool hooks log and time web_search calls, Tokyo population query |
