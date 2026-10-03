"""60db workspace voice synthesis.

Configure SIXTYDB_API_KEY and SIXTYDB_VOICE_ID on the agent server.
This example sends its speech text to the selected hosted provider.
No extra provider SDK is required.
"""

from os import environ
from pathlib import Path

from agno.agent import Agent
from agno.tools.sixtydb import SixtyDBTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Speech Agent",
    tools=[SixtyDBTools(default_voice_id=environ["SIXTYDB_VOICE_ID"])],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run(
        "Use text_to_speech to say: Welcome. How can I help you today?"
    )
    if response.audio and response.audio[0].content:
        Path("greeting.wav").write_bytes(response.audio[0].content)
