"""
Agent Sets It Up
================

Give an agent MonitorTools and it starts watches from a sentence. It may name any
path freely -- a path is data -- but a shell command must be one the operator
declared, so a prompt injection cannot turn this into shell access.

Prerequisites: OPENAI_API_KEY and pip install agno watchfiles
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/06_agent_sets_it_up.py
Try: Run this file with --demo in another terminal (or --chat to type your own)
"""

import sys
import time
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.monitor import MonitorConfig, MonitorManager
from agno.os import AgentOS
from agno.tools.monitor import MonitorTools

JOB = "cookbook/05_agent_os/26_monitor/_noisy_job.py"

db = SqliteDb(id="monitor-tools-demo", db_file="tmp/monitor_tools_demo.db")

WATCH_COMMANDS = {
    "app_errors": "tail -F tmp/app.log | grep --line-buffered ERROR",
    "orders_job": f"{sys.executable} {JOB} 2>&1 | grep --line-buffered -E 'ERROR|Traceback|Error'",
    "disk_usage": "while true; do df -h / | tail -1; sleep 30; done",
}

WATCH_DESCRIPTIONS = {
    "app_errors": "lines containing ERROR as they are appended to tmp/app.log",
    "orders_job": "the orders batch job, emitting an event only when it raises an error",
    "disk_usage": "free space on the root filesystem, sampled every 30 seconds",
}

WATCH_ROOT = "tmp/watched_code"

monitor_agent = Agent(
    id="monitor-agent",
    name="Monitor Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[MonitorTools(db=db, watches=WATCH_DESCRIPTIONS, base_dir=WATCH_ROOT)],
    instructions=[
        "You help the user watch long-running things in the background.",
        "To watch files or folders, use watch_files with a path -- you may name any path you like.",
        "For anything else, start the declared watch that covers it.",
        "If no declared watch covers the request, say so and start nothing.",
        "Use get_watch to report what condition a watch is in and get_watch_events to show what it caught.",
    ],
    db=db,
)

agent_os = AgentOS(
    name="Monitor Tools OS",
    agents=[monitor_agent],
    db=db,
    monitors=MonitorConfig(
        watch_commands=WATCH_COMMANDS,
        base_dir=WATCH_ROOT,
        poll_interval=5,
    ),
)
app = agent_os.get_app()


def chat() -> None:
    """Interactive chat with the monitor agent."""
    print("Chat with the Monitor Agent (type 'quit' to exit)")
    print("Try: 'Watch the orders job and tell me if it errors'")
    print("Or:  'Watch the reports folder and tell me when a file changes'")
    print("-" * 50)
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message.lower() in ("quit", "exit"):
            break
        monitor_agent.print_response(message)


def demo() -> None:
    """Show both halves of the mapping form: a match, then an honest refusal."""
    import httpx

    # Every tool here only WRITES a monitor row. What runs one is the poller the
    # server starts, so without terminal 1 nothing the agent starts ever fires.
    try:
        httpx.get("http://127.0.0.1:7777/health", timeout=5)
    except httpx.ConnectError:
        print("No AgentOS on http://127.0.0.1:7777.")
        print("Start it first, in another terminal:")
        print("    python cookbook/05_agent_os/26_monitor/06_agent_sets_it_up.py")
        return

    # A path watch is refused if the path is not there, so the folder the demo
    # asks about has to exist before it asks.
    (Path(WATCH_ROOT) / "reports").mkdir(parents=True, exist_ok=True)
    monitor_agent.print_response(
        "Watch the orders job and tell me if it errors. Give me the monitor id."
    )
    monitor_agent.print_response(
        "Now watch our Postgres replication lag and alert me if a replica falls behind."
    )
    monitor_agent.print_response(
        "Also keep an eye on the reports folder and tell me whenever a file in it changes."
    )

    # The rows are written; give the poller a moment and show what actually ran.
    print("\nWaiting for the poller to run what the agent started...")
    time.sleep(20)
    manager = MonitorManager(db=db)
    for monitor in manager.list(status=None):
        print(f"\n  {monitor.name}: {monitor.status}, {monitor.event_count} event(s)")
        for event in reversed(manager.get_events(monitor.id, limit=3)):
            print(f"    {event.seq}: {event.content.strip()}")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    elif "--chat" in sys.argv:
        chat()
    else:
        agent_os.serve(app=app)
