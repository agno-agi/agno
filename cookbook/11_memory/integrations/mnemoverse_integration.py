"""
Mnemoverse Integration
======================

Demonstrates using Mnemoverse as an external memory service for an Agno agent.

After the run, the example rates the memories that were in the prompt, so the
memory service learns which ones helped.

Setup: create a key at https://console.mnemoverse.com/dashboard/keys and
export it as MNEMOVERSE_API_KEY.
"""

from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIChat
from agno.utils.pprint import pprint_run_response

try:
    from mnemoverse import MnemoClient
except ImportError:
    raise ImportError(
        "mnemoverse is not installed. Please install it using `uv pip install mnemoverse`."
    )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
client = MnemoClient()

domain = "agno"
notes = [
    "My name is John Billings.",
    "I live in NYC.",
    "I'm going to a concert tomorrow.",
]

# Comment out the following lines after running the script once
for note in notes:
    client.write(note, domain=domain)

recalled = client.recent(domain=domain, limit=10)
memory = [item.content for item in recalled.items]


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(),
    dependencies={"memory": memory},
    add_dependencies_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run: RunOutput = agent.run("What do you know about me?")
    pprint_run_response(run)

    # Rate the memories that were in the prompt: 1.0 helped, -1.0 misled.
    if recalled.items:
        client.feedback(
            atom_ids=[item.atom_id for item in recalled.items],
            outcome=1.0,
            domain=domain,
        )
