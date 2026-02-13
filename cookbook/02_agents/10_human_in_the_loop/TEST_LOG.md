# Test Log — 10_human_in_the_loop

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| agentic_user_input.py | SKIP | HITL - validated startup, hits EOFError at input() prompt as expected |
| confirmation_advanced.py | SKIP | HITL - validated startup, hits EOFError at confirmation prompt |
| confirmation_required.py | SKIP | HITL - validated startup, hits EOFError at confirmation prompt |
| confirmation_required_mcp_toolkit.py | SKIP | HITL - validated startup, hits EOFError at confirmation prompt |
| confirmation_toolkit.py | SKIP | HITL - validated startup, hits EOFError at confirmation prompt |
| external_tool_execution.py | SKIP | HITL - agent ran but shell command rejected (pwd && ls -la unsupported) |
| user_input_required.py | SKIP | HITL - validated startup, hits EOFError at input() prompt |
