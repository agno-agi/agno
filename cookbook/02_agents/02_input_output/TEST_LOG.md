# Test Log — 02_input_output

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| expected_output.py | PASS | Agent returns clean code principles as expected output |
| input_formats.py | PASS | Multi-format input with image URL, agent describes landscape |
| input_schema.py | PASS | Structured input schema with HackerNewsTools, timeout on HN fetch but agent handled gracefully |
| output_model.py | PASS | Returns detailed Pad Thai recipe as structured output model |
| output_schema.py | PASS | Agent uses search_news tool and returns structured France news |
| parser_model.py | PASS | Returns structured Yellowstone travel guide via parser model |
| response_as_variable.py | PASS | RunOutput captured with tool_calls, session_state, RunStatus.completed |
| save_to_file.py | PASS | Response saved to tmp/agent_output.md |
| streaming.py | PASS | Streaming response about concurrency vs parallelism |
