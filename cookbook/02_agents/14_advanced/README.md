# 14_advanced

Advanced examples covering caching, compression, concurrency, events, retries, debugging, and serialization.

## Files
- `advanced_compression.py` - Advanced context compression strategies.
- `agent_run_cancel_persistence.py` - Cancel a running agent and verify partial content is persisted.
- `agent_serialization.py` - Serialize and deserialize agents.
- `background_execution.py` - Run agents in the background.
- `background_execution_structured.py` - Background execution with structured output.
- `basic_agent_events.py` - Listen to agent lifecycle events.
- `cache_model_response.py` - Cache model responses.
- `cancel_run.py` - Cancel a running agent.
- `compression_events.py` - Events during context compression.
- `concurrent_execution.py` - Run multiple agents concurrently.
- `custom_cancellation_manager.py` - Custom cancellation logic.
- `custom_logging.py` - Custom logging configuration.
- `debug.py` - Enable debug mode for verbose output.
- `metrics.py` - Access agent run metrics.
- `reasoning_agent_events.py` - Events during reasoning steps.
- `retries.py` - Retry configuration with exponential backoff.
- `tool_call_compression.py` - Compress tool call results in context.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/14_advanced/<file>.py`


### Domain-aware follow-ups

`followup_instructions.py` uses `FollowupConfig` with an agent that answers only
Python documentation questions. The same configuration works on `Team`.
`FollowupConfig.model` takes precedence over `followup_model`, then the main model.
Only the question, answer and follow-up instructions are sent to this call; the
main system prompt and retrieved evidence are not copied automatically.

`num_followups` is a maximum. The default prompt respects refusals and permits
fewer suggestions or `[]`; malformed generation still produces `None`. Streaming
completion events and persisted run output preserve the list, including `[]`.
Consumers should hide suggestion controls for an empty list.
