"""
Compaction Events
=================

Compaction is observable: a CompactionStarted / CompactionCompleted event pair
fires around every pass, carrying token counts — never summary text. On a
streamed run the events arrive live; with store_events=True they also persist
on the run.

Run: .venvs/demo/bin/python cookbook/02_agents/23_context_compaction/03_compaction_events.py
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunEvent

agent = Agent(
    id="compaction-events-demo",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=SqliteDb(db_file="tmp/compaction.db"),
    add_history_to_context=True,
    # background=False makes the pass synchronous so this demo's events are
    # deterministic; with the default the fold runs early, in the background.
    compaction=Compaction(context_window=6_000, background=False),
    store_events=True,
    markdown=True,
)

session_id = "compaction-events-session"

prompts = [
    "Walk me through TCP congestion control in detail.",
    "Now explain how QUIC changes that picture, in detail.",
    "Compare their behavior on a lossy mobile link.",
    "What should a video call application pick, and why?",
]

for prompt in prompts:
    for event in agent.run(
        prompt, session_id=session_id, stream=True, stream_events=True
    ):
        if event.event == RunEvent.compaction_started.value:
            print(
                f"\n[compaction started: reason={event.reason} tokens_before={event.tokens_before}]"
            )
        elif event.event == RunEvent.compaction_completed.value:
            print(
                f"[compaction completed: {event.tokens_before} -> {event.tokens_after} tokens, "
                f"record {event.record_id}]"
            )
        elif event.event == RunEvent.run_content.value and event.content:
            print(event.content, end="")
    print()
