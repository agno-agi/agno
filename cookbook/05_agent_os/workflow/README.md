# Workflow Cookbook

Examples for `workflow` in AgentOS.

## Files
- `basic_chat_workflow_agent.py` — Example demonstrating how to add a Workflow using a WorkflowAgent to your AgentOS.
- `basic_workflow.py` — Basic Workflow.
- `basic_workflow_team.py` — Basic Workflow Team.
- `customer_research_workflow_parallel.py` — Customer Research Workflow Parallel.
- `workflow_with_conditional.py` — Workflow With Conditional.
- `workflow_with_custom_function.py` — Workflow With Custom Function Executors.
- `workflow_with_custom_function_updating_session_state.py` — Workflow With Custom Function Updating Session State.
- `workflow_with_history.py` — Workflow With History.
- `workflow_with_input_schema.py` — Workflow With Input Schema.
- `workflow_with_loop.py` — Workflow With Loop.
- `workflow_with_nested_steps.py` — Workflow With Nested Steps.
- `workflow_with_parallel.py` — Workflow With Parallel.
- `workflow_with_parallel_and_custom_function_step_stream.py` — Workflow With Parallel And Custom Function Step Stream.
- `workflow_with_router.py` — Workflow With Router.
- `workflow_with_steps.py` — Workflow With Steps.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
