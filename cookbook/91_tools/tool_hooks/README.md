# tool_hooks

Cookbook examples for using Agno tool hooks to wrap tool execution.

Tool hooks receive the tool name, arguments, and continuation function before the
tool body runs. This makes them the provider-neutral integration point for
deterministic tool governance patterns such as allow/deny policy checks, audit
receipts, result redaction, and local kill switches.

## Examples

- `tool_hook.py` - Log before and after a standalone tool call.
- `tool_hook_in_toolkit.py` - Authorize and transform toolkit tool calls.
- `tool_hooks_in_toolkit_nested.py` - Compose multiple hooks in sync and async paths.
- `deterministic_governance.py` - Enforce allow/deny policy, PII redaction, a per-agent call budget, and a kill switch without adding a governance provider dependency.
