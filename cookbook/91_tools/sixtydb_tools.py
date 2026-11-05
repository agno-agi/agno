"""60db workspace voice synthesis.

Set SIXTYDB_API_KEY and your agent model's credentials. Optionally set
SIXTYDB_VOICE_ID; otherwise get_voices selects the first available workspace
voice. The example saves generated audio to tmp/greeting.wav.
"""

import base64
import json
from os import getenv

from agno.agent import Agent
from agno.tools.sixtydb import SixtyDBTools
from agno.utils.audio import write_audio_to_file

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
tools = SixtyDBTools(default_voice_id=getenv("SIXTYDB_VOICE_ID"))

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not tools.default_voice_id:
        # Workspace voices differ between accounts; get_voices lists valid IDs.
        voices = json.loads(tools.get_voices())
        if not isinstance(voices, list) or not voices:
            print(
                "No workspace voice available. Check SIXTYDB_API_KEY and get_voices()."
            )
            raise SystemExit(1)
        tools.default_voice_id = voices[0]["voice_id"]
        print(f"Using workspace voice: {tools.default_voice_id}")
    agent = Agent(name="Speech Agent", tools=[tools])
    response = agent.run(
        "Use text_to_speech to say: Welcome. How can I help you today?"
    )
    if response.audio and response.audio[0].content:
        write_audio_to_file(
            audio=base64.b64encode(response.audio[0].content),
            filename="tmp/greeting.wav",
        )
        print("Audio saved to tmp/greeting.wav")
    else:
        print(
            "No audio returned. Check the synthesis error above and your workspace voice ID."
        )
