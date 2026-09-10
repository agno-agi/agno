# Responses

Cookbook examples for `cookbook/90_models/openai/responses`.

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/openai/responses/<example>.py
```

## Store responses without automatic chaining

`stored_responses_without_chaining.py` uses `store=True` to keep responses in
OpenAI's response logs and `use_previous_response_id=False` to send the context
assembled by Agno on every request. Agno's history limits and current instructions
therefore control the request even when prior messages contain response IDs.

```python
model=OpenAIResponses(
    id="gpt-5.6-luna",
    store=True,
    use_previous_response_id=False,
)
```

The option defaults to `True`, preserving automatic chaining for supported
reasoning models when `store` is not `False`. Setting `store=False` continues to
disable provider response storage and automatic chaining. History must still be
enabled on the agent if it should include previous turns.

When automatic chaining is disabled, Agno also preserves and replays encrypted
reasoning alongside tool calls. Low-level `request_params` overrides retain their
existing precedence; leave `previous_response_id` unset there when using this option.

See [OpenAI's conversation state guide](https://developers.openai.com/api/docs/guides/conversation-state)
for response storage and manual history management.
