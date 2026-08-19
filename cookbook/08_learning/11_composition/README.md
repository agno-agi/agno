# 11_composition

The manual door. `learning=` is the automatic door: pass it and the framework
attaches context, instructions and tools at fixed positions. Don't pass it,
and the framework attaches nothing - you place the machine's three public
surfaces yourself, the way FileSystem composes. Read this folder next to
`00_quickstart` to see the two doors side by side.

## Files

- `basic.py`: tools=[*learning.get_tools()] + instructions=[learning.instructions()].
- `with_filesystem.py`: LearningMachine + FileSystem + your own system prompt,
  in one deliberate order.
- `context_block.py`: build_context() placed via additional_context - data
  without tools.
- `always_capture.py`: post_hooks=[learning.capture_hook()] - ALWAYS-mode
  extraction through the manual door (the escape hatch).

## The three surfaces

| Surface | Returns | Place it in |
|---|---|---|
| `learning.get_tools(user_id=...)` | the capture tools | `tools=[...]` |
| `learning.instructions()` | the guidance block | `instructions=[...]` |
| `learning.build_context(user_id=..., message=...)` | the recalled data | `additional_context` / a dependency |

The manual door injects nothing - give the machine its `db` and its `model`
explicitly. Every capture path is a model call: without one, `update_profile`
and `update_user_memory` return "No model provided", `capture_hook`'s ALWAYS
extraction stores nothing, and entity memory keeps every stated fact instead of
retiring the ones it contradicts. `get_tools()` warns once when a store is in
that state.

The manual door is agentic by nature: with no `learning=` there is no
automatic post-run extraction, and the tools are the capture mechanism.
Passing the same machine to `learning=` AND placing its surfaces by hand
renders the blocks twice - the framework warns once when it detects that.
