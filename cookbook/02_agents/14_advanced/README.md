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
`FollowupConfig` carries custom instructions and an optional separate model.
`FollowupConfig.model` takes precedence over `followup_model`, then the main model;
either slot accepts a `Model` object or a `provider:model_id` string, resolved when
the component is built. Only the question, answer and follow-up instructions are
sent to this call; the main instructions, retrieved evidence and history are not
copied as separate context, but anything already in the user input or the answer
still reaches the follow-up model.

`num_followups` is a maximum: a successful result holds zero to N suggestions,
excess suggestions are clipped, and `[]` is a valid result. The default prompt asks
the model to respect refusals and stay within the answer's scope; this is prompt
guidance, not enforcement, and it applies to every `followups=True` component, with
or without a `FollowupConfig`. Failed, cancelled or malformed generation produces
`None`. Streaming completion events and persisted run output preserve the list,
including `[]`. Consumers should hide suggestion controls for an empty list.

`to_dict()` and `from_dict()` on `Agent` and `Team` keep `followups`, `num_followups`,
`followup_model` and `followup_config`. A model is stored by identity only (`id`,
`name`, `provider`), never with credentials; register the live model in a `Registry`
to keep custom endpoints or connection settings when the component is recreated.
