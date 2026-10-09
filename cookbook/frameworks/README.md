# Framework adapters

Use AgentOS with a program built in another agent framework:

- [LangGraph](langgraph/): graph execution, tools, sessions and checkpoint examples.
- [DSPy](dspy/): prediction and ReAct programs with Agno run output.

For coding harnesses, start with the new
[Claude and Codex walkthrough](../harnesses/README.md). Harnesses own their
native agent loop and context; framework adapters have their own state contracts.
A common HTTP API does not imply identical persistence or recovery capabilities.

The migration is incremental. Advanced [Claude](claude-agent-sdk/README.md),
[Codex](codex/README.md), [Antigravity](antigravity/README.md), and the older
[mixed-framework quickstart](00_quickstart/README.md) remain at their existing
paths. Their historical test results are separate from the new harness suite.

All built-in adapters share the [3.2 API migration](../harnesses/README.md#adapter-api-changes-for-32):
keyword-only configuration, read-only `sdk` metadata, failure-aware printing,
and explicit rejection of unsupported media inputs.
