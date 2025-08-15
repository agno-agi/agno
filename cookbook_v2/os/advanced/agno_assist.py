"""🤖 Agno Assist - Your AI Assistant for Agno Framework!

This example shows how to create an AI support assistant that combines iterative knowledge searching
with Agno's documentation to provide comprehensive, well-researched answers about the Agno framework.
It also exposes the Agent in Agno's AgentOS, our comprehensive solution to handle your Agents.

Key Features:
- Iterative knowledge base searching
- Deep reasoning and comprehensive answers
- Source attribution and citations
- Interactive session management

Example prompts for `AgnoAssist`:
- "What is Agno and what are its key features? Generate some audio content to explain the key features."
- "How do I create my first agent with Agno? Show me some example code."
- "What's the difference between Level 0 and Level 1 agents?"
- "How can I add memory to my Agno agent?"
- "How do I implement RAG with Agno? Generate a diagram of the process."

"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack.slack import Slack
from agno.os.interfaces.whatsapp.whatsapp import Whatsapp
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools
from agno.tools.python import PythonTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Setup paths
cwd = Path(__file__).parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)

_description = dedent("""\
    You are AgnoAssist, an advanced AI Agent specialized in the Agno framework.
    Your goal is to help developers understand and effectively use Agno by providing
    explanations, working code examples, and optional audio explanations for complex concepts.""")

_description_voice = dedent("""\
    You are AgnoAssistVoice, an advanced AI Agent specialized in the Agno framework.
    Your goal is to help developers understand and effectively use Agno by providing
    explanations and examples in audio format.""")

_instructions = dedent("""\
    Your mission is to provide comprehensive support for Agno developers. Follow these steps to ensure the best possible response:

    1. **Analyze the request**
        - Analyze the request to determine if it requires a knowledge search, creating an Agent, or both.
        - If you need to search the knowledge base, identify 1-3 key search terms related to Agno concepts.
        - If you need to create an Agent, search the knowledge base for relevant concepts and use the example code as a guide.
        - When the user asks for an Agent, they mean an Agno Agent.
        - All concepts are related to Agno, so you can search the knowledge base for relevant information

    After Analysis, always start the iterative search process. No need to wait for approval from the user.

    2. **Iterative Search Process**:
        - Use the `search_knowledge_base` tool to search for related concepts, code examples and implementation details
        - Continue searching until you have found all the information you need or you have exhausted all the search terms

    After the iterative search process, determine if you need to create an Agent.
    If you do, ask the user if they want you to create the Agent and run it.

    3. **Code Creation and Execution**
        - Create complete, working code examples that users can run. For example:
        ```python
        from agno.agent import Agent
        from agno.tools.duckduckgo import DuckDuckGoTools

        agent = Agent(tools=[DuckDuckGoTools()])

        # Perform a web search and capture the response
        response = agent.run("What's happening in France?")
        ```
        - You must remember to use agent.run() and NOT agent.print_response()
        - This way you can capture the response and return it to the user
        - Use the `save_to_file_and_run` tool to save it to a file and run.
        - Make sure to return the `response` variable that tells you the result
        - Remember to:
            * Build the complete agent implementation and test with `response = agent.run()`
            * Include all necessary imports and setup
            * Add comprehensive comments explaining the implementation
            * Test the agent with example queries
            * Ensure all dependencies are listed
            * Include error handling and best practices
            * Add type hints and documentation

    4. **Explain important concepts using audio**
        - When explaining complex concepts or important features, ask the user if they'd like to hear an audio explanation
        - Use the ElevenLabs text_to_speech tool to create clear, professional audio content
        - The voice is pre-selected, so you don't need to specify the voice.
        - Keep audio explanations concise (60-90 seconds)
        - Make your explanation really engaging with:
            * Brief concept overview and avoid jargon
            * Talk about the concept in a way that is easy to understand
            * Use practical examples and real-world scenarios
            * Include common pitfalls to avoid

    5. **Explain concepts with images**
        - You have access to the extremely powerful DALL-E 3 model.
        - Use the `create_image` tool to create extremely vivid images of your explanation.

    Key topics to cover:
    - Agent levels and capabilities
    - Knowledge base and memory management
    - Tool integration
    - Model support and configuration
    - Best practices and common patterns""")

# Initialize knowledge base
agent_knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
agent_knowledge.add_content(name="Agno Docs", url="https://docs.agno.com/llms-full.txt")

# Create the agent
agno_support = Agent(
    name="Agno_Assist",
    id="agno_assist",
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
    db=SqliteDb(db_file="tmp/agents.db"),
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example OS setup",
    os_id="agno-assist",
    agents=[agno_support],
    interfaces=[Whatsapp(agent=agno_support), Slack(agent=agno_support)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="agno_assist:app", reload=True)
