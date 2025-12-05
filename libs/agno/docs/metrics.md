# Metrics System Documentation

## Overview

The Agno framework uses a four-tier metrics architecture to track performance and token consumption at different levels of granularity:

1. **ToolCallMetrics** - Time-only metrics for individual tool executions
2. **MessageMetrics** - Token consumption and timing for individual assistant messages
3. **Metrics** (Run-Level) - Aggregated metrics for an entire agent run, with per-model breakdown
4. **SessionMetrics** - Aggregated metrics across all runs in a session

```
┌─────────────────────────────────────────────────────────────┐
│                    SessionMetrics                            │
│  (Aggregated across all runs, per-model breakdown)          │
└───────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
┌───────▼────────┐              ┌───────▼────────┐
│    Metrics     │              │    Metrics     │
│   (Run 1)      │              │   (Run 2)      │
│                │              │                │
│  details: {    │              │  details: {    │
│    "model":    │              │    "model":    │
│    "output":   │              │    "output":   │
│    "reasoning" │              │    "reasoning" │
│  }             │              │  }             │
└───────┬────────┘              └───────┬────────┘
        │                               │
        └───────────────┬───────────────┘
                        │
        ┌───────────────┴───────────────┐
        │                               │
┌───────▼────────┐              ┌───────▼────────┐
│ MessageMetrics │              │ MessageMetrics │
│ (assistant msg)│              │ (assistant msg)│
└────────────────┘              └────────────────┘
```

## Metrics Classes Deep Dive

### 1. ToolCallMetrics

**Purpose**: Track execution time for individual tool calls. Contains only time-related fields, no token information.

**Fields**:
- `timer: Optional[Timer]` - Internal timer utility
- `start_time: Optional[float]` - Unix timestamp when tool execution started
- `end_time: Optional[float]` - Unix timestamp when tool execution ended
- `duration: Optional[float]` - Total execution time in seconds

**When Created**: During tool execution in `run_function_calls` method
- Timer starts when tool execution begins
- Timer stops when tool execution completes
- Duration is calculated from timer elapsed time

**Location**: `ToolExecution.metrics` field

**Key Files**:
- `libs/agno/agno/models/metrics.py:32-70` - ToolCallMetrics class definition
- `libs/agno/agno/models/base.py:2197` - Tool execution with metrics tracking

**Example**:
```python
tool_execution = ToolExecution(
    tool_name="search_web",
    metrics=ToolCallMetrics()
)
tool_execution.metrics.start_timer()
# ... execute tool ...
tool_execution.metrics.stop_timer()
# duration is now set
```

### 2. MessageMetrics

**Purpose**: Track token consumption and timing for individual assistant messages. Only set on assistant messages from model responses.

**Fields**:
- **Token metrics**: `input_tokens`, `output_tokens`, `total_tokens`
- **Audio tokens**: `audio_input_tokens`, `audio_output_tokens`, `audio_total_tokens`
- **Cache tokens**: `cache_read_tokens`, `cache_write_tokens`
- **Reasoning tokens**: `reasoning_tokens`
- **Time metrics**: 
  - `timer: Optional[Timer]` - Internal timer utility
  - `time_to_first_token: Optional[float]` - Time from message start to first token generation (seconds)
  - `duration: Optional[float]` - Total message processing time (seconds)

**When Created**: Before model API calls via `_ensure_message_metrics_initialized` helper method

**Location**: `Message.metrics` field (only on assistant messages)

**Key Files**:
- `libs/agno/agno/models/metrics.py:73-162` - MessageMetrics class definition
- `libs/agno/agno/models/base.py:306-317` - `_ensure_message_metrics_initialized` helper
- `libs/agno/agno/models/base.py:823-911` - `_populate_assistant_message` method

**Timing Flow**:
1. **Before API call**: `_ensure_message_metrics_initialized` creates `MessageMetrics()` and calls `start_timer()`
2. **During API call**: Provider response contains usage data
3. **After API call**: `_populate_assistant_message` updates MessageMetrics with token counts from `provider_response.response_usage`
4. **First content chunk**: `set_time_to_first_token()` is called when first content is received
5. **After response**: `stop_timer()` is called, setting `duration`

**Important Notes**:
- User, system, and tool messages have `metrics = None`
- Only assistant messages from model responses have MessageMetrics
- Token counts come from the provider's usage response
- `time_to_first_token` is set on the first content chunk received (streaming or non-streaming)

**Example**:
```python
# In model.response() or model.response_stream()
assistant_message = Message(role="assistant")
assistant_message.metrics = MessageMetrics()
assistant_message.metrics.start_timer()

# Make API call...
# Provider returns usage data

# Update metrics with token counts
assistant_message.metrics.input_tokens = usage.input_tokens
assistant_message.metrics.output_tokens = usage.output_tokens

# When first content arrives:
assistant_message.metrics.set_time_to_first_token()

# After response complete:
assistant_message.metrics.stop_timer()
```

### 3. Metrics (Run-Level)

**Purpose**: Aggregate metrics for an entire agent run, with per-model breakdown in the `details` field.

**Fields**:
- **Aggregated token metrics**: `input_tokens`, `output_tokens`, `total_tokens` (summed from all models)
- **Audio/Cache/Reasoning tokens**: Aggregated from all models
- **Time metrics**:
  - `timer: Optional[Timer]` - Run-level timer (starts at run start)
  - `time_to_first_token: Optional[float]` - Minimum time_to_first_token from all models
  - `duration: Optional[float]` - Total run time
- **Per-model breakdown**: `details: Optional[Dict[str, List[ModelMetrics]]]`
  - Keys: `"model"`, `"output_model"`, `"reasoning_model"`, `"parser_model"`
  - Values: Lists of `ModelMetrics` (one per model instance, supports future fallback models)

**When Created**: 
- At run start: `Metrics()` created and timer started
- Updated after model calls: `_calculate_run_metrics` aggregates from message lists

**Location**: `RunOutput.metrics` field

**Key Files**:
- `libs/agno/agno/models/metrics.py:339-467` - Metrics class definition
- `libs/agno/agno/agent/agent.py:1727` - Run metrics initialization
- `libs/agno/agno/agent/agent.py:8903-9115` - `_calculate_run_metrics` method

**Details Structure**:
The `details` dictionary maps model types to lists of `ModelMetrics`:

```python
details = {
    "model": [
        ModelMetrics(
            id="gpt-4o",
            provider="OpenAI",
            input_tokens=157,
            output_tokens=365,
            total_tokens=522,
            time_to_first_token=2.4
        )
    ],
    "output_model": [
        ModelMetrics(
            id="o3-mini",
            provider="OpenAI",
            input_tokens=170,
            output_tokens=621,
            total_tokens=791,
            time_to_first_token=4.9
        )
    ],
    "reasoning_model": [...],
    "parser_model": [...]
}
```

**Top-Level Aggregation**:
- `input_tokens`, `output_tokens`, `total_tokens`: Summed from all models in `details`
- `time_to_first_token`: Minimum value from all models (first model to generate tokens)
- Only includes models that were actually used in the run

**Calculation Flow**:
1. Run starts: `Metrics()` created, `start_timer()` called
2. After model calls: `_calculate_run_metrics` receives message lists by model type
3. For each model type:
   - Filter assistant messages with metrics
   - Aggregate MessageMetrics using `__add__` operator
   - Create `ModelMetrics` entry with model id, provider, and aggregated tokens
   - Add to `details` dictionary
4. Calculate top-level aggregates by summing from `details`
5. Set `time_to_first_token` to minimum from all models

**Example**:
```python
# Run starts
run_response.metrics = Metrics()
run_response.metrics.start_timer()

# After model calls complete
run_response.metrics = agent._calculate_run_metrics(
    model_messages=run_messages.messages,
    output_model_messages=run_messages.output_model_messages,
    reasoning_model_messages=run_messages.reasoning_model_messages,
    parser_model_messages=run_messages.parser_model_messages,
    current_run_metrics=run_response.metrics  # Preserves timer
)

# Access metrics
print(run_response.metrics.total_tokens)  # Sum from all models
print(run_response.metrics.details["model"][0].total_tokens)  # Main model only
```

### 4. SessionMetrics

**Purpose**: Aggregate metrics across all runs in a session. Excludes run-level timing fields like `duration` and `time_to_first_token` (uses `average_duration` instead).

**Fields**:
- **Aggregated token metrics**: `input_tokens`, `output_tokens`, `total_tokens` (summed from all runs)
- **Audio/Cache/Reasoning tokens**: Aggregated from all runs
- **Session-level stats**:
  - `average_duration: Optional[float]` - Weighted average duration across all runs
  - `total_runs: int` - Total number of runs in session
- **Per-model breakdown**: `details: Optional[List[SessionModelMetrics]]`
  - One entry per unique `(provider, id)` combination
  - Aggregates tokens and calculates weighted average duration per model

**When Created**: Updated after each run in `_update_session_metrics`

**Location**: `AgentSession.session_data["session_metrics"]` (stored as dict)

**Key Files**:
- `libs/agno/agno/models/metrics.py:192-336` - SessionMetrics class definition
- `libs/agno/agno/agent/agent.py:8700-8870` - `_update_session_metrics` method

**Details Structure**:
The `details` list contains `SessionModelMetrics` objects, one per unique model:

```python
details = [
    SessionModelMetrics(
        id="gpt-4o",
        provider="OpenAI",
        input_tokens=1287,
        output_tokens=87,
        total_tokens=1374,
        average_duration=6.45,
        total_runs=2
    ),
    SessionModelMetrics(
        id="o3-mini",
        provider="OpenAI",
        input_tokens=500,
        output_tokens=200,
        total_tokens=700,
        average_duration=3.2,
        total_runs=1
    )
]
```

**Aggregation Flow**:
1. After each run: `_update_session_metrics` called with `RunOutput`
2. Token aggregation: Adds run tokens to session totals
3. Duration averaging: Calculates weighted average: `(old_avg * old_count + new_duration) / new_count`
4. Per-model details: Merges by `(provider, id)` combination
   - If model exists: Aggregates tokens, updates weighted average duration, increments `total_runs`
   - If new model: Creates new `SessionModelMetrics` entry

**Example**:
```python
session_metrics = agent.get_session_metrics()
print(session_metrics.total_runs)  # Total runs in session
print(session_metrics.average_duration)  # Weighted average
print(session_metrics.details[0].total_runs)  # Runs using this specific model
```

## Message Structure and Relationships

### Message Class

The `Message` class represents individual messages in a conversation. It has an optional `metrics` field that is only populated for assistant messages from model responses.

**Key Fields**:
- `role: str` - One of "system", "user", "assistant", or "tool"
- `content: Optional[Union[List[Any], str]]` - Message content
- `metrics: Optional[MessageMetrics]` - **Only set on assistant messages**

**Key File**: `libs/agno/agno/models/message.py:52-449`

**Important Rules**:
- User messages: `metrics = None`
- System messages: `metrics = None`
- Tool messages: `metrics = None`
- Assistant messages from model responses: `metrics = MessageMetrics()` (with token and timing data)

### RunMessages Container

The `RunMessages` dataclass organizes messages by model type to enable separate metrics tracking for different models used in a run.

**Fields**:
- `messages: List[Message]` - All messages (main model messages)
- `system_message: Optional[Message]` - System message for the run
- `user_message: Optional[Message]` - User message for the run
- `extra_messages: Optional[List[Message]]` - Extra messages added after system/user
- `output_model_messages: List[Message]` - Messages generated by `output_model` (separate from main model)
- `reasoning_model_messages: List[Message]` - Messages generated by `reasoning_model` (separate from main model)
- `parser_model_messages: List[Message]` - Messages generated by `parser_model` (separate from main model)

**Key File**: `libs/agno/agno/run/messages.py`

**Purpose**: Allows metrics calculation to distinguish between:
- Main model messages (in `messages`)
- Output model messages (in `output_model_messages`)
- Reasoning model messages (in `reasoning_model_messages`)
- Parser model messages (in `parser_model_messages`)

### Message Flow

Messages flow through the system differently depending on which model generates them:

#### Main Model Messages
- Created during `model.response()` or `model.response_stream()`
- Added to `run_messages.messages` list
- Assistant messages have `MessageMetrics` populated
- Used for main model metrics calculation

#### Output Model Messages
- Created when `output_model` is used to refine/format the main model's response
- Messages extracted from a **copy** of the main messages (last assistant message removed)
- New assistant message added to the copy during `output_model.response()`
- Extracted and added to `run_messages.output_model_messages`
- Key file: `libs/agno/agno/agent/agent.py:9976-9992`

**Extraction Logic**:
```python
messages_for_output_model = _get_messages_for_output_model(run_messages.messages)  # Creates copy
initial_count = len(messages_for_output_model)
output_model_response = output_model.response(messages=messages_for_output_model)
# New assistant message added to messages_for_output_model
output_model_messages = messages_for_output_model[initial_count:]  # Extract new messages
run_messages.output_model_messages.extend(output_model_messages)
```

#### Reasoning Model Messages
- Created when `reasoning_model` is used for chain-of-thought reasoning
- Reasoning agent runs in separate context, returns a `Message` with reasoning content
- Message extracted from reasoning agent's `RunOutput.messages`
- Added to `run_messages.reasoning_model_messages`
- Metrics extracted from reasoning agent's response and adjusted for main run timing
- Key file: `libs/agno/agno/agent/agent.py:9607-9620`, `libs/agno/agno/reasoning/openai.py:28-163`

**Special Timing Adjustment**:
Since the reasoning agent runs in its own context with its own timer, the `time_to_first_token` must be adjusted to be relative to the main run start:
```python
reasoning_start_elapsed_time = main_run_metrics.timer.elapsed  # Captured right before calling reasoning agent
adjusted_time_to_first_token = reasoning_start_elapsed_time + reasoning_agent_time_to_first_token
```

#### Parser Model Messages
- Created when `parser_model` is used to parse structured output
- Only tracked when `output_schema` is provided
- Messages extracted after parser model response completes
- Added to `run_messages.parser_model_messages`
- Key file: `libs/agno/agno/agent/agent.py:9769-9794`

## Metrics Generation Flow

### MessageMetrics Generation

MessageMetrics are created and populated during the model response process:

**Non-Streaming Flow** (`model.response()`):
1. **Before API call**: `_ensure_message_metrics_initialized(assistant_message)` called
   - Creates `MessageMetrics()` if None
   - Calls `start_timer()` to begin timing
2. **API call**: Model provider API called with messages
3. **Response received**: Provider returns response with usage data
4. **Populate metrics**: `_populate_assistant_message` updates MessageMetrics:
   - Token counts from `provider_response.response_usage`
   - `set_time_to_first_token()` called when content is received
5. **Stop timer**: `stop_timer()` called, sets `duration`

**Streaming Flow** (`model.response_stream()`):
1. **Before API call**: `stream_data.response_metrics = MessageMetrics()` created
   - `start_timer()` called
2. **Streaming chunks**: `_populate_stream_data` processes each chunk
   - Token counts accumulated from usage deltas
   - `set_time_to_first_token()` called on first content chunk
3. **Stream complete**: Timer stopped, metrics finalized
4. **Final message**: Metrics copied to assistant message

**Key Files**:
- `libs/agno/agno/models/base.py:306-317` - `_ensure_message_metrics_initialized` helper
- `libs/agno/agno/models/base.py:823-911` - `_populate_assistant_message` (non-streaming)
- `libs/agno/agno/models/base.py:1400-1417` - `_populate_stream_data` (streaming)

### Run Metrics Calculation

Run-level metrics are calculated in `_calculate_run_metrics`:

**Process**:
1. **Run starts**: `Metrics()` created, `start_timer()` called at run start
2. **After model calls**: `_calculate_run_metrics` receives message lists by model type
3. **Per-model processing**:
   - Filter assistant messages with metrics (exclude `from_history=True` messages)
   - Aggregate MessageMetrics using `__add__` operator (sums tokens, takes first `time_to_first_token`)
   - Create `ModelMetrics` entry with:
     - Model `id` and `provider`
     - Aggregated token counts
     - First `time_to_first_token` from messages
   - Add to `details` dictionary under model type key
4. **Top-level aggregation**:
   - Sum `input_tokens`, `output_tokens`, `total_tokens` from all models in `details`
   - Set `time_to_first_token` to minimum from all models
5. **Preserve timing**: If `current_run_metrics` provided, preserve `timer` and `duration`

**Key File**: `libs/agno/agno/agent/agent.py:8903-9115`

**Example Calculation**:
```python
# Main model messages
main_messages = [msg for msg in model_messages if msg.role == "assistant" and msg.metrics]
aggregated = MessageMetrics()
for msg in main_messages:
    aggregated += msg.metrics  # Sums tokens, takes first time_to_first_token

model_metrics = ModelMetrics(
    id=self.model.id,
    provider=self.model.get_provider(),
    input_tokens=aggregated.input_tokens,
    output_tokens=aggregated.output_tokens,
    total_tokens=aggregated.total_tokens,
    time_to_first_token=first_time_to_first_token
)
details["model"] = [model_metrics]
```

### Session Metrics Aggregation

Session metrics are updated after each run completes:

**Process**:
1. **After run**: `_update_session_metrics` called with `RunOutput`
2. **Load existing**: `_get_session_metrics` retrieves or creates `SessionMetrics`
3. **Token aggregation**: Adds run tokens to session totals
4. **Duration averaging**: Calculates weighted average:
   ```python
   total_duration = (old_avg * old_count) + new_duration
   new_avg = total_duration / new_count
   ```
5. **Per-model details**: For each model in run's `details`:
   - Look up by `(provider, id)` in session `details`
   - If exists: Aggregate tokens, update weighted average duration, increment `total_runs`
   - If new: Create new `SessionModelMetrics` entry
6. **Persist**: Store in `session.session_data["session_metrics"]` as dict

**Key File**: `libs/agno/agno/agent/agent.py:8700-8870`

**Merging Logic**:
```python
# Merge by (provider, id) key
for run_model_metrics in run_metrics.details["model"]:
    found = False
    for session_model_metrics in session_metrics.details:
        if (session_model_metrics.id == run_model_metrics.id and 
            session_model_metrics.provider == run_model_metrics.provider):
            # Aggregate existing
            session_model_metrics.input_tokens += run_model_metrics.input_tokens
            session_model_metrics.total_runs += 1
            # Update weighted average duration
            # ...
            found = True
            break
    if not found:
        # Add new model
        session_metrics.details.append(SessionModelMetrics(...))
```

## Special Cases and Nuances

### Reasoning Model Timing

The reasoning model presents a special challenge because it runs in a separate agent context with its own timer.

**Problem**: The reasoning agent's `time_to_first_token` is relative to when the reasoning agent's run started, not the main agent's run start.

**Solution**: Capture the elapsed time from the main run right before calling the reasoning agent, then adjust:

```python
# In reasoning function (e.g., aget_openai_reasoning)
reasoning_start_elapsed_time = main_run_metrics.timer.elapsed  # Time from main run start
reasoning_agent_response = await reasoning_agent.arun(...)
reasoning_time_to_first_token = reasoning_agent_response.messages[0].metrics.time_to_first_token

# Adjust to be relative to main run start
adjusted_time_to_first_token = reasoning_start_elapsed_time + reasoning_time_to_first_token
```

**Key File**: `libs/agno/agno/reasoning/openai.py:28-163`

**Important**: The elapsed time must be captured **right before** calling the reasoning agent to account for any overhead between when we decide to call reasoning and when it actually starts.

### Output Model Messages

The output model receives a modified copy of the main messages to generate refined output.

**Process**:
1. `_get_messages_for_output_model` creates a **copy** of `run_messages.messages` (to avoid mutating original)
2. Removes the last assistant message (main model's response)
3. Optionally modifies system message with `output_model_prompt`
4. `output_model.response()` called with this modified copy
5. New assistant message added to the copy
6. Extract new messages: `messages_for_output_model[initial_count:]`
7. Add to `run_messages.output_model_messages`

**Key File**: `libs/agno/agno/agent/agent.py:8558-8577`, `9976-9992`

**Why Copy**: Prevents mutating the original `run_messages.messages` list, which could cause issues with metrics calculation.

### Parser Model Messages

The parser model is only used when `output_schema` is provided and is called after the main model (or output model) generates a response.

**Process**:
1. Check if `output_schema` exists in `run_context`
2. Create messages for parser model (includes main model's response)
3. Call `parser_model.response()` or `parser_model.response_stream()`
4. Extract assistant message from parser model's response
5. Add to `run_messages.parser_model_messages`

**Key File**: `libs/agno/agno/agent/agent.py:9769-9794`, `9848-9909`

**Note**: Parser model messages are tracked separately so their metrics don't get mixed with main model metrics.

### Streaming vs Non-Streaming

Both streaming and non-streaming follow the same metrics initialization pattern, but use different storage locations:

**Non-Streaming**:
- MessageMetrics stored on `assistant_message.metrics`
- Timer starts before API call
- Metrics updated after response received

**Streaming**:
- MessageMetrics stored on `stream_data.response_metrics`
- Timer starts before streaming begins
- Metrics updated incrementally as chunks arrive
- `time_to_first_token` set on first content chunk
- Final metrics copied to assistant message when stream completes

**Key Files**:
- `libs/agno/agno/models/base.py:319-390` - Non-streaming `response()`
- `libs/agno/agno/models/base.py:521-600` - Streaming `aresponse()`
- `libs/agno/agno/models/base.py:1400-1417` - Streaming metrics update

## Serialization and Persistence

### to_dict() Methods

All metrics classes implement `to_dict()` methods that:
- Remove internal utilities (e.g., `timer` objects)
- Filter out `None` values and empty collections
- Convert nested objects to dicts
- Filter out deprecated fields (for backward compatibility)

**Example**:
```python
metrics_dict = run_output.metrics.to_dict()
# {
#   "input_tokens": 157,
#   "output_tokens": 365,
#   "total_tokens": 522,
#   "time_to_first_token": 2.4,
#   "duration": 5.6,
#   "details": {
#     "model": [{"id": "gpt-4o", "provider": "OpenAI", ...}]
#   }
# }
```

### Session Metrics Persistence

Session metrics are stored in the database as part of `AgentSession.session_data`:

```python
session.session_data["session_metrics"] = session_metrics.to_dict()
```

When loading, `_get_session_metrics` deserializes:
- Handles legacy `Metrics` dicts (converts to `SessionMetrics`)
- Deserializes `details` list back to `SessionModelMetrics` objects
- Removes run-level timing fields (`duration`, `time_to_first_token`)

**Key File**: `libs/agno/agno/agent/agent.py:8620-8700`

### Backward Compatibility

The system handles legacy metrics structures:
- Old `Metrics` objects without `details` field
- Old session metrics stored as `Metrics` instead of `SessionMetrics`
- Deprecated fields like `provider_metrics` and `additional_metrics` are filtered out

## Code Examples

### Accessing Run Metrics

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o"))
run_output = agent.run("Hello")

# Access top-level aggregates
print(run_output.metrics.total_tokens)  # Sum from all models
print(run_output.metrics.duration)  # Total run time
print(run_output.metrics.time_to_first_token)  # First model's time_to_first_token

# Access per-model details
if run_output.metrics.details:
    for model_type, model_metrics_list in run_output.metrics.details.items():
        print(f"{model_type}:")
        for model_metrics in model_metrics_list:
            print(f"  {model_metrics.id} ({model_metrics.provider}):")
            print(f"    Tokens: {model_metrics.total_tokens}")
            print(f"    Time to first token: {model_metrics.time_to_first_token}")
```

### Accessing Message Metrics

```python
run_output = agent.run("Hello")

# Only assistant messages have metrics
for message in run_output.messages:
    if message.role == "assistant" and message.metrics:
        print(f"Message tokens: {message.metrics.total_tokens}")
        print(f"Time to first token: {message.metrics.time_to_first_token}")
        print(f"Duration: {message.metrics.duration}")
```

### Accessing Session Metrics

```python
session_metrics = agent.get_session_metrics()

print(f"Total runs: {session_metrics.total_runs}")
print(f"Average duration: {session_metrics.average_duration}")
print(f"Total tokens: {session_metrics.total_tokens}")

# Per-model breakdown
if session_metrics.details:
    for model_metrics in session_metrics.details:
        print(f"{model_metrics.id} ({model_metrics.provider}):")
        print(f"  Total tokens: {model_metrics.total_tokens}")
        print(f"  Used in {model_metrics.total_runs} runs")
        print(f"  Average duration: {model_metrics.average_duration}")
```

### Accessing Tool Metrics

```python
run_output = agent.run("Search for Python tutorials")

if run_output.tools:
    for tool in run_output.tools:
        if tool.metrics:
            print(f"Tool: {tool.tool_name}")
            print(f"  Duration: {tool.metrics.duration}")
            print(f"  Start time: {tool.metrics.start_time}")
            print(f"  End time: {tool.metrics.end_time}")
```

## Summary

The metrics system provides comprehensive tracking at four levels:

1. **ToolCallMetrics**: Execution time for individual tools
2. **MessageMetrics**: Token consumption and timing for assistant messages
3. **Metrics**: Run-level aggregation with per-model breakdown
4. **SessionMetrics**: Cross-run aggregation with per-model session stats

Key principles:
- Metrics are only set where relevant (tools → time, assistant messages → tokens + time)
- Per-model tracking enables accurate attribution when multiple models are used
- Timing is carefully tracked relative to appropriate start points
- Session metrics aggregate across runs while preserving per-model breakdowns

