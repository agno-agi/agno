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

`followups` takes `False`, `True` for the defaults, or a `FollowupConfig` that enables
follow-ups and carries the count, custom instructions and an optional separate model.
The top-level arguments still work on their own: `followups=True` with `num_followups`
or `followup_model`. Use one form or the other: passing a `FollowupConfig` together
with `num_followups` or `followup_model` raises `ValueError`.

| You write | You get |
|---|---|
| `followups=True` | exactly 3 suggestions |
| `followups=True, num_followups=5` | exactly 5 |
| `FollowupConfig()` | exactly 3, the same as `True` |
| `FollowupConfig(num_followups=5)` | exactly 5 |
| `FollowupConfig(max_followups=3)` | up to 3, possibly none |
| `FollowupConfig(min_followups=1, max_followups=3)` | 1 to 3 |
| `FollowupConfig(min_followups=1)` | 1 to 3 (the maximum defaults to 3) |

Inside the config, set the count with `num_followups` or with `min_followups` and
`max_followups`, not both. The maximum is enforced: extra suggestions are dropped. The
minimum is only requested from the model, so fewer can come back. With
`max_followups` alone, the model may return nothing when a declined request leaves no
useful in-scope continuation, so consumers should hide suggestion controls for an
empty list. Failed, cancelled or malformed generation produces `None`.

Every component with follow-ups enabled gets a prompt that asks the model to respect
refusals and stay within the answer's scope. This is prompt guidance, not enforcement.
Only the question, answer and follow-up instructions are sent to this call; the main
instructions, retrieved evidence and history are not copied as separate context.
Either model slot accepts a `Model` object or a `provider:model_id` string, resolved
when the component is built.

`to_dict()` and `from_dict()` on `Agent` and `Team` keep the follow-up settings in
whichever form was used. A follow-up model is stored by identity only (`id`, `name`,
`provider`), never with credentials or request headers; register the live model in a
`Registry` to keep custom endpoints or connection settings when the component is
recreated.
