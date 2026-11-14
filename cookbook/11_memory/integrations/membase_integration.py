"""
Membase Integration
===================

Demonstrates using Membase as an external memory service for an Agno agent.

Membase keeps a person's memory in named Memories that several AI tools can
share. Every search result names the Memory it came from, so the agent can say
where it learned a fact.

Setup: create a key at https://app.membase.com (Connect > Developer keys) that
reaches one Memory, and export it as MEMBASE_API_KEY.
"""

from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIChat
from agno.utils.pprint import pprint_run_response

try:
    from membase import Membase
except ImportError:
    raise ImportError(
        "membase is not installed. Please install it using `uv pip install unibaseio-membase`."
    )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
client = Membase()

notes = [
    "My name is John Billings.",
    "I live in NYC.",
    "I'm going to a concert tomorrow.",
]

# Comment out the following lines after running the script once
for note in notes:
    client.memories.add(note)

# Membase learns new notes in the background; if nothing comes back, wait a
# moment and run the script again.
results = client.search("What do you know about the user?", limit=10)
memory = [f"[{item['memory_name']}] {item['content']}" for item in results["items"]]


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(),
    instructions="When you use a fact from memory, say which Memory it came from.",
    dependencies={"memory": memory},
    add_dependencies_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run: RunOutput = agent.run("What do you know about me?")
    pprint_run_response(run)
