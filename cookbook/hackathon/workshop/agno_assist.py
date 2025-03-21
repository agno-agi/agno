"""pip install openai lancedb sqlalchemy elevenlabs tantivy fastapi"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools
from agno.tools.python import PythonTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Setup paths
cwd = Path(__file__).parent.parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)

# Initialize knowledge base
agent_knowledge = UrlKnowledge(
    urls=["https://docs.agno.com/llms-full.txt"],
    vector_db=LanceDb(
        uri=str(tmp_dir.joinpath("lancedb")),
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

_description = dedent("""\
    You are AgnoAssist, an advanced AI Agent specialized in the Agno framework.
    Your goal is to help developers understand and effectively use Agno.""")

_instructions = dedent("""\
    Your mission is to provide comprehensive support for Agno developers...""")

agent_knowledge.load(recreate=False)

agno_support = Agent(
    name="Agno_Assist",
    agent_id="agno_assist",
    model=OpenAIChat(id="gpt-4o"),
    description=_description,
    instructions=_instructions,
    knowledge=agent_knowledge,
    tools=[
        PythonTools(base_dir=tmp_dir.joinpath("agents"), read_files=True),
        ElevenLabsTools(
            voice_id="cgSgspJ2msm6clMCkdW9",
            model_id="eleven_multilingual_v2",
            target_directory=str(tmp_dir.joinpath("audio").resolve()),
        ),
        DalleTools(model="dall-e-3", size="1792x1024", quality="hd", style="vivid"),
    ],
    storage=SqliteStorage(
        table_name="agno_assist_sessions", db_file=str(tmp_dir.joinpath("agents.db"))
    ),
    markdown=True,
    search_knowledge=True,
    debug_mode=True,
)

# agno_support.print_response("How do I implement RAG with Agno? Generate a diagram of the process.", stream=True)


"""
Example prompts for `AgnoAssist`:
- "What is Agno and what are its key features? Generate some audio content to explain the key features."
- "How do I create my first agent with Agno? Show me some example code."
- "What's the difference between Level 0 and Level 1 agents?"
- "How can I add memory to my Agno agent?"
- "How do I implement RAG with Agno? Generate a diagram of the process."
"""
