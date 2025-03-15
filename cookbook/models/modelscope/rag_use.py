from agno.agent import Agent
from agno.models.modelscope import ModelScope
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.text import TextKnowledgeBase
from agno.vectordb.lancedb import LanceDb, SearchType

agent = Agent(
    model=ModelScope(id="Qwen/Qwen2.5-72B-Instruct"),
    description="You are an expert in information at Albert College!",
    instructions=[
        "Search for information about Albert College in your knowledge base.",
        "You need to rely on the information in the knowledge base"
    ],
    knowledge=TextKnowledgeBase(
        path="./test_knowledge.txt",
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="recipes",
            embedder=OpenAIEmbedder(id="text-embedding-3-small")
        ),
    ),
    tools=[],
    show_tool_calls=True,
    markdown=True,
    system_message_role="system",
)

# Comment out after the knowledge base is loaded
if agent.knowledge is not None:
    agent.knowledge.load()

agent.print_response("Who is the president of Albert College?", stream=True)