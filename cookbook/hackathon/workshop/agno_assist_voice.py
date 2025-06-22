from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.python import PythonTools
from agno_assist import agent_knowledge

cwd = Path(__file__).parent.parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)


_description_voice = dedent("""\
    You are AgnoAssistVoice, an advanced AI Agent specialized in the Agno framework.""")

_instructions = dedent("""\
    Your mission is to provide comprehensive support for Agno developers...""")

agno_assist_voice = Agent(
    name="Agno_Assist_Voice",
    agent_id="agno-assist-voice",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "pcm16"},
    ),
    description=_description_voice,
    instructions=_instructions,
    knowledge=agent_knowledge,
    tools=[PythonTools(base_dir=tmp_dir.joinpath("agents"), read_files=True)],
    storage=SqliteStorage(
        table_name="agno_assist_voice_sessions",
        db_file=str(tmp_dir.joinpath("agents.db")),
    ),
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    markdown=True,
)

# agno_assist_voice.print_response("Hello, I am Agno Assist Voice. How can I help you?")

"""
Example prompts for `AgnoAssistVoice`:
- "What is Agno and what are its key features?"
- "How do I create my first agent with Agno?"
- "What's the difference between Level 0 and Level 1 agents?"
- "What models does Agno support?"
"""
