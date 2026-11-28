"""
Shared Session Between Agents
=============================

Several agents take part in one session, like a group chat. Every agent runs on the
same session_id with shared_session=True, so each one sees the others' replies,
labelled with their name, and never mistakes them for its own.

A user message is one Message object run through each addressed agent. By default it
goes to every agent. Pass to= to address one agent; the others still see that exchange
on their next turn, because it lives in the shared session.
"""

from typing import List, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.models.openai import OpenAIResponses

db = SqliteDb(db_file="tmp/agents.db")
session_id = f"room-{uuid4()}"


def make_agent(name: str, role: str) -> Agent:
    return Agent(
        name=name,
        model=OpenAIResponses(id="gpt-5.6-luna"),
        db=db,
        add_history_to_context=True,
        # Each user turn produces one run per agent, so count runs generously.
        num_history_runs=20,
        shared_session=True,
        instructions=[
            f"You are {name}, one of several agents in a group chat with a user.",
            role,
            "Other agents' messages appear as '<Name>: ...'. Keep replies to two or three sentences",
            "and refer to the others by name when you build on or disagree with them.",
        ],
        markdown=False,
    )


researcher = make_agent("Researcher", "You bring facts and concrete options.")
skeptic = make_agent("Skeptic", "You look for risks and weak assumptions.")
writer = make_agent("Writer", "You turn the discussion into clear, final wording.")
agents = [researcher, skeptic, writer]


def say(text: str, to: Optional[List[Agent]] = None) -> None:
    """Send one user message to every agent, or only to the agents in `to`."""
    turn = Message(role="user", content=text)
    print(f"\nUser: {text}")
    for agent in to or agents:
        response = agent.run(turn, session_id=session_id)
        print(f"\n{agent.name}: {response.content}")


# Everyone replies to the opening message.
say("We are planning a three day trip to Kyoto in November. Thoughts?")

# Only the Skeptic is addressed. The others see this exchange on their next turn.
say("Skeptic, what is the single biggest risk with this plan?", to=[skeptic])

# Only the Writer is addressed, and it can use the Skeptic's answer.
say("Writer, fold the Skeptic's concern into a one paragraph plan.", to=[writer])

# Back to everyone.
say("Any last objections before we book?")

# The stored session holds one run per agent reply. A broadcast turn keeps one
# Message id across its runs, which is how the agents replay it once.
print("\n--- Stored transcript ---")
session = researcher.get_session(session_id=session_id)
last_turn_id = None
for run in session.runs or []:
    user_message = next(
        (m for m in run.messages or [] if m.role == "user" and not m.from_history), None
    )
    if user_message is not None and user_message.id != last_turn_id:
        last_turn_id = user_message.id
        print(f"\nUser: {user_message.get_content_string()}")
    print(f"{run.agent_name}: {run.content}")
