from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.postgres import PostgresStorage
from agno.workflow.v2.step import Step
from agno.workflow.v2.workflow import Workflow
from pydantic import BaseModel, Field

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


# Define response format
class Source(BaseModel):
    name: str = Field(description="The name of the source")
    page_number: int = Field(description="The page number of the source")


class Response(BaseModel):
    response: str = Field(description="The response to the user's query")
    sources: list[Source] = Field(
        description="The sources used to generate the response"
    )


# Define agents
information_agent = Agent(
    name="Information Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Gathers sufficient context from the user regarding their query",
)

knowledge_search_agent = Agent(
    name="Knowledge Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Searches the knowledge base for relevant information to answer the user's query",
    # knowledge=knowledge, # Commented out for now, but will have its own knowledge base
)

response_agent = Agent(
    name="Response Agent",
    model=OpenAIChat(id="gpt-4o"),
    role="Respond to the user's query based on the provided information and sources",
    response_model=Response,
)

# Define steps
information_gather_step = Step(
    name="Research Step",
    agent=information_agent,
)

knowledge_search_step = Step(
    name="Knowledge Search Step",
    agent=knowledge_search_agent,
)

response_step = Step(
    name="Response Step",
    agent=response_agent,
)

# Create and use workflow
if __name__ == "__main__":
    rag_workflow = Workflow(
        name="RAG Workflow",
        description="A RAG workflow tasked with answering user queries based on a provided knowledge base.",
        storage=PostgresStorage(
            table_name="workflow_v2",
            db_url=db_url,
            mode="workflow_v2",
        ),
        steps=[information_gather_step, knowledge_search_step, response_step],
    )
    rag_workflow.print_response(
        message="What is the latest news in AI?",
        markdown=True,
    )
