# Issue: Thinking tokens don't stream when response_model is set on Agno team with Anthropic models

## Description
When `response_model` is set on an Agno team using Anthropic (Claude) models, thinking tokens arrive in bulk instead of streaming progressively. This affects the user experience as they don't see the model's reasoning process in real-time.

## Current Behavior
- When `response_model` is set, ALL streaming is disabled (including thinking tokens)
- The entire response (thinking + content) is collected before being returned
- Users see thinking tokens appear all at once after processing is complete

## Expected Behavior
- Thinking tokens should stream in real-time, even when `response_model` is set
- Only the actual response content needs to be buffered for structured output parsing
- Users should see the model's reasoning process as it happens

## Root Cause
In `/Users/jonathan/dev/agno/libs/agno/agno/team/team.py` (lines 1811-1814), when `should_parse_structured_output` is `True` (which happens when `response_model` is set), the code completely disables streaming:

```python
stream_model_response = True
if self.should_parse_structured_output:
    log_debug("Response model set, model response is not streamed.")
    stream_model_response = False
```

This causes the model's `response_stream` method to use `_process_model_response` instead of streaming, which makes a non-streaming API call and returns everything at once.

## Technical Details
- Thinking tokens come through as `thinking_delta` events in Claude's streaming response
- These are separate from the actual content (`text_delta`) that needs to be parsed
- The current implementation unnecessarily blocks both types of streaming

## Proposed Solution
Modify the streaming behavior to:
1. **Always stream thinking tokens** - Allow `thinking_delta` events to pass through immediately
2. **Buffer only response content** - Collect `text_delta` events when `response_model` is set
3. **Parse at completion** - Once streaming ends, parse the buffered content against the `response_model`

### Implementation Areas
1. **`_handle_model_response_stream` method**: Instead of disabling all streaming, enable selective streaming
2. **`_handle_model_response_chunk` method**: Differentiate between thinking and content events
3. **Model's `response_stream`**: Support partial streaming mode that streams thinking but buffers content

## Impact
- Improves user experience by showing reasoning in real-time
- Maintains structured output validation functionality
- Affects all teams using `response_model` with reasoning-capable models (Claude, OpenAI o1, etc.)

## Reproduction Steps
1. Create an Agno team with Claude model (e.g., `claude-3-5-sonnet`)
2. Set a `response_model` on the team (any Pydantic model)
3. Enable thinking/reasoning
4. Run the team with streaming enabled
5. Observe that thinking tokens arrive all at once instead of streaming

## Priority
Medium - This affects user experience but doesn't break functionality