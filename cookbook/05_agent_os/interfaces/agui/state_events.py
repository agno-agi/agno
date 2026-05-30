"""
AG-UI State Events
==================

Demonstrates outbound state synchronization via STATE_SNAPSHOT + STATE_DELTA events.

When a frontend (e.g. CopilotKit) provides `state` on an AG-UI request, the agent
receives it as `session_state` and can mutate it via tools. This example shows how
agno emits:

- `STATE_SNAPSHOT` — the full state, sent once after RUN_STARTED (so the client
  has a baseline) and once before RUN_FINISHED (so the client has the final state)
- `STATE_DELTA` — RFC 6902 JSON Patch ops describing each mutation, emitted after
  every tool call that changes the session_state

This enables real-time UI updates: as the agent works on a todo list, edits a
document, or progresses through a multi-step task, the frontend can re-render
each piece without polling or requesting full state dumps.

Test with curl (a request that provides initial state and lets the agent mutate it):

    curl -N -X POST http://localhost:9001/agui \\
      -H 'content-type: application/json' \\
      -d '{
        "threadId":"t1",
        "runId":"r1",
        "state":{"todos":[],"counter":0},
        "messages":[{"id":"m1","role":"user","content":"Add 3 items to the todo list"}],
        "tools":[],
        "context":[],
        "forwardedProps":{}
      }'

In the SSE response you should see `data: {"type":"STATE_SNAPSHOT",...}` near the
top (initial state), `data: {"type":"STATE_DELTA","delta":[...]}` after each tool
call that mutated state, and another `STATE_SNAPSHOT` near the end (final state).
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.run import RunContext


def add_todo(run_context: RunContext, task: str) -> str:
    """Append a task to the session todos list.

    Args:
        task: The todo item to append
    """
    if run_context.session_state is None:
        run_context.session_state = {}
    todos = run_context.session_state.setdefault("todos", [])
    todos.append(task)
    return f"Added: {task} (total {len(todos)})"


def bump_counter(run_context: RunContext) -> int:
    """Increment the counter in session state."""
    if run_context.session_state is None:
        run_context.session_state = {}
    run_context.session_state["counter"] = (
        run_context.session_state.get("counter", 0) + 1
    )
    return run_context.session_state["counter"]


agent = Agent(
    name="StateAwareAssistant",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=(
        "You help the user maintain a todo list and a counter, both stored in session state. "
        "Use the add_todo tool to append items and bump_counter to increment the counter."
    ),
    tools=[add_todo, bump_counter],
    markdown=True,
)

agent_os = AgentOS(agents=[agent], interfaces=[AGUI(agent=agent)])
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="state_events:app", reload=True, port=9001)
