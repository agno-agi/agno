from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools
from agno.vectordb.pgvector import PgVector, SearchType

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# *******************************

# ************* Paths *************
cwd = Path(__file__).parent
knowledge_dir = cwd.joinpath("knowledge")
output_dir = cwd.joinpath("output")

# Create the output directory if it does not exist
output_dir.mkdir(parents=True, exist_ok=True)
# *******************************

# ************* Description & Instructions *************
description = dedent("""\
    You are AgnoAssist, an advanced AI Agent specialized in the Agno framework.
    Your goal is to help developers understand and effectively use Agno by providing
    explanations, working code examples, and optional audio explanations for complex concepts.""")

instructions = dedent("""\
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

    3. **Code Creation**
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
        - Remember to:
            * Build the complete agent implementation
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
        - Don't provide the URL of the image in the response. Only describe what image was generated.

    Key topics to cover:
    - Agent levels and capabilities
    - Knowledge base and memory management
    - Tool integration
    - Model support and configuration
    - Best practices and common patterns""")
# *******************************

# Create the agent
agno_assist = Agent(
    name="Agno Assist",
    agent_id="agno-assist",
    model=OpenAIChat(id="gpt-4o"),
    description=description,
    instructions=instructions,
    memory=Memory(
        model=OpenAIChat(id="gpt-4.1"),
        db=PostgresMemoryDb(table_name="user_memories", db_url=db_url),
        delete_memories=True,
        clear_memories=True,
    ),
    enable_agentic_memory=True,
    knowledge=UrlKnowledge(
        urls=["https://docs.agno.com/llms-full.txt"],
        vector_db=PgVector(
            db_url=db_url,
            table_name="agno_assist_knowledge",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    ),
    search_knowledge=True,
    storage=PostgresAgentStorage(
        db_url=db_url,
        table_name="agno_assist_sessions",
    ),
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    markdown=True,
    tools=[
        ElevenLabsTools(
            voice_id="cgSgspJ2msm6clMCkdW9",
            model_id="eleven_multilingual_v2",
            target_directory=str(output_dir.joinpath("audio").resolve()),
        ),
        DalleTools(model="dall-e-3", size="1792x1024", quality="hd", style="vivid"),
    ],
)
