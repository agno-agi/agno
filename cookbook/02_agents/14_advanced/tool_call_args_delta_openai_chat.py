"""
Tool Call Args Delta — OpenAI Chat
===================================

Stream tool call arguments as they are generated, using OpenAI Chat Completions.
ToolCallArgsDelta events emit incremental argument fragments in real-time,
enabling UIs to show tool call arguments as they are being built by the model.

Run with:
    .venvs/demo/bin/python cookbook/02_agents/14_advanced/tool_call_args_delta_openai_chat.py
"""

import json

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunEvent


def create_task(title: str, description: str, assignee: str, priority: str, due_date: str, tags: list[str]) -> str:
    """Create a task with the given details."""
    return json.dumps({
        "status": "created",
        "task": {
            "title": title,
            "description": description,
            "assignee": assignee,
            "priority": priority,
            "due_date": due_date,
            "tags": tags,
        },
    })


def collect_and_print_deltas(agent, prompt, label):
    """Run agent with streaming and collect/print ToolCallArgsDelta events."""
    delta_events = []
    other_events = []

    for chunk in agent.run(prompt, stream=True):
        if hasattr(chunk, "event"):
            if chunk.event == RunEvent.tool_call_args_delta.value:
                delta_events.append(chunk)
                print(f"  [ToolCallArgsDelta] index={chunk.tool_call_index} "
                      f"id={chunk.tool_call_id} name={chunk.tool_call_name} "
                      f"delta='{chunk.arguments_delta}'")
            elif chunk.event in (
                RunEvent.tool_call_started.value,
                RunEvent.tool_call_completed.value,
            ):
                other_events.append(chunk)
                print(f"  [{chunk.event}]")

    print(f"\n  ToolCallArgsDelta events: {len(delta_events)}")
    print(f"  ToolCallStarted/Completed events: {len(other_events)}")

    if delta_events:
        args_by_index = {}
        for evt in delta_events:
            idx = evt.tool_call_index or 0
            if idx not in args_by_index:
                args_by_index[idx] = {"id": evt.tool_call_id, "name": evt.tool_call_name, "args": ""}
            if evt.tool_call_id:
                args_by_index[idx]["id"] = evt.tool_call_id
            if evt.tool_call_name:
                args_by_index[idx]["name"] = evt.tool_call_name
            args_by_index[idx]["args"] += evt.arguments_delta

        print("\n  Reconstructed tool calls from deltas:")
        for idx, info in args_by_index.items():
            print(f"    Tool[{idx}]: name={info['name']}, id={info['id']}")
            try:
                parsed = json.loads(info["args"])
                print(f"      args={json.dumps(parsed)}")
            except json.JSONDecodeError:
                print(f"      raw args={info['args']}")

        print(f"\n  PASS ({label})")
    else:
        print(f"\n  FAIL ({label}): No ToolCallArgsDelta events received.")

    return delta_events


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
task_agent = Agent(
    model=OpenAIChat(id="gpt-5.4"),
    tools=[create_task],
    instructions="You are a task manager. Use the create_task tool to create tasks.",
    stream=True,
    stream_events=True,
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== OpenAIChat: ToolCallArgsDelta streaming ===\n")
    collect_and_print_deltas(
        task_agent,
        "Create a task: title='Implement OAuth2 login flow', "
        "description='Add Google and GitHub OAuth2 providers to the authentication service "
        "with proper token refresh handling and session management', "
        "assignee='alice@example.com', priority='high', due_date='2026-05-01', "
        "tags=['auth', 'backend', 'security', 'oauth2']",
        "OpenAIChat",
    )
