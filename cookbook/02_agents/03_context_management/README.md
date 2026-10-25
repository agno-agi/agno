# 03_context_management

Examples for instructions, system messages, introduction messages, and context shaping.

## Files
- `compaction/compaction.py` - Keep a long session in the context window with `compaction=True`.
- `compaction/compaction_thresholds.py` - Tune when compaction fires and how much it keeps.
- `compaction/compaction_manual.py` - Fold now with `agent.compact()`, and read the status when it declines.
- `compaction/compaction_token_counter.py` - Choose how tokens are counted: the local default, the model's own count with `use_model_token_count=True`, or any tokenizer such as Hugging Face.
- `compaction/compaction_async_token_counter.py` - Count tokens on the async path: an async `token_counter` awaited in `arun`, here the model's count plus a safety margin.
- `compaction/compaction_tail_budget.py` - Bound the kept tail by size with `uncompacted_tokens`, for agents whose turns vary in length.
- `compaction/compaction_threshold_room.py` - Size `compact_at_tokens` so a fold leaves room: too small folds every run (and warns), sized well folds every few runs.
- `compaction/compaction_searchable_archive.py` - Let the agent search history that was compacted away.
- `compaction/compaction_events.py` - Stream `CompactionStarted` / `CompactionCompleted` and show what was reclaimed.
- `compaction/compaction_async.py` - Compaction on the async path.
- `compaction/compaction_with_tools.py` - Folding a transcript that contains tool calls, without splitting a call from its result.
- `compaction/compaction_anthropic.py` - The same folding on Claude, which carries history in the request rather than by id.
- `compaction/compaction_anthropic_thinking.py` - Extended thinking plus tool calls, the hardest shape for a cut to respect.
- `few_shot_learning.py` - Demonstrates few-shot learning with example messages.
- `filter_tool_calls_from_history.py` - Filter tool calls from conversation history.
- `instructions.py` - Set agent instructions.
- `instructions_with_state.py` - Dynamic instructions using session state.
- `introduction_message.py` - Set an initial greeting message for the agent.
- `system_message.py` - Customize the agent's system message and role.
- `datetime_format.py` - Customize the datetime format injected into agent context.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/03_context_management/<file>.py`
