import os

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai.chat import OpenAIChat
from agno.os import AgentOS
from agno.tools.notion import NotionTools
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel


# Pydantic model for classification output
class ClassificationResult(BaseModel):
    query: str
    tag: str
    message: str


# Agents
notion_agent = Agent(
    name="Notion Manager",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        NotionTools(
            api_key=os.getenv("NOTION_API_KEY", ""),
            database_id=os.getenv("NOTION_DATABASE_ID", ""),
        )
    ],
    instructions=[
        "You are a Notion page manager.",
        "You will receive instructions with a query and a pre-classified tag.",
        "CRITICAL: Use ONLY the exact tag provided in the instructions. Do NOT create new tags or modify the tag name.",
        "The valid tags are: travel, tech, general-blogs, fashion, documents",
        "Workflow:",
        "1. Search for existing pages with the EXACT tag provided",
        "2. If a page exists: Update that page with the new query content",
        "3. If no page exists: Create a new page using the EXACT tag provided",
        "Always preserve the exact tag name as given in the instructions.",
    ],
)


# Executor functions
# Step 1: Custom classifier function to assign tags
def classify_query(step_input: StepInput) -> StepOutput:
    """
    Classify the user query into one of the predefined tags.

    Available tags: travel, tech, general-blogs, fashion, documents
    """
    # Get the user query from step_input
    query = step_input.input

    # Create an agent to classify the query
    classifier_agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "You are a query classifier.",
            "Classify the given query into ONE of these tags: travel, tech, general-blogs, fashion, documents",
            "Only respond with the tag name, nothing else.",
            "Classification rules:",
            "- travel: Anything related to destinations, tours, trips, locations, hotels, travel guides, places to visit",
            "- tech: Programming, software, AI, machine learning, coding, development, technology topics",
            "- fashion: Clothing, style, trends, outfits, fashion industry",
            "- documents: Resumes, CVs, reports, official documents, contracts",
            "- general-blogs: Personal thoughts, opinions, life advice, miscellaneous content",
            "",
            "Examples:",
            "- 'Best places to visit in Italy' -> travel",
            "- 'Ha Giang loop tour Vietnam guide' -> travel",
            "- 'Add travel guide website link' -> travel",
            "- 'How to build a React app' -> tech",
            "- 'The rise of AI and machine learning' -> tech",
            "- 'Fashion trends 2025' -> fashion",
            "- 'My resume and CV' -> documents",
            "- 'Random thoughts about life' -> general-blogs",
        ],
    )

    # Get classification
    response = classifier_agent.run(query)
    tag = response.content.strip().lower()

    # Validate the tag
    valid_tags = ["travel", "tech", "general-blogs", "fashion", "documents"]
    if tag not in valid_tags:
        tag = "general-blogs"  # Default fallback

    # Return structured data using Pydantic model
    result = ClassificationResult(
        query=str(query), tag=tag, message=f"Query classified as: {tag}"
    )

    return StepOutput(content=result)


# Custom function to prepare input for Notion agent
def prepare_notion_input(step_input: StepInput) -> StepOutput:
    """
    Extract the classification result and format it for the Notion agent.
    """
    # Get the classification result from the previous step (Classify Query)
    previous_output = step_input.previous_step_content

    # Parse it into our Pydantic model if it's a dict
    if isinstance(previous_output, dict):
        classification = ClassificationResult(**previous_output)
    elif isinstance(previous_output, str):
        # If it's a string, try to parse it or use the original input
        import json

        try:
            classification = ClassificationResult(**json.loads(previous_output))
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            classification = ClassificationResult(
                query=str(step_input.input),
                tag="general-blogs",
                message="Failed to parse classification",
            )
    else:
        classification = previous_output

    # Create a clear instruction for the Notion agent with EXPLICIT tag requirement
    instruction = f"""Process this classified query:

        Query: {classification.query}
        Tag: {classification.tag}

        IMPORTANT: You MUST use the tag "{classification.tag}" (one of: travel, tech, general-blogs, fashion, documents).
        Do NOT create a new tag. Use EXACTLY "{classification.tag}".

        Instructions:
        1. Use search_pages tool to find pages with tag "{classification.tag}"
        2. If page exists: Use update_page to add the query content
        3. If no page exists: Use create_page with title "My {classification.tag.title()} Collection", tag "{classification.tag}", and the query as content

        The tag MUST be exactly: {classification.tag}
    """

    return StepOutput(content=instruction)


# Steps
classify_step = Step(
    name="Classify Query",
    executor=classify_query,
    description="Classify the user query into a tag category",
)

notion_prep_step = Step(
    name="Prepare Notion Input",
    executor=prepare_notion_input,
    description="Format the classification result for the Notion agent",
)

notion_step = Step(
    name="Manage Notion Page",
    agent=notion_agent,
    description="Create or update Notion page based on query and tag",
)

# Create the workflow
query_to_notion_workflow = Workflow(
    name="query-to-notion-workflow",
    description="Classify user queries and organize them in Notion",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
    steps=[classify_step, notion_prep_step, notion_step],
)

# Initialize the AgentOS
agent_os = AgentOS(
    description="Query classification and Notion organization system",
    workflows=[query_to_notion_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="notion_manager:app", reload=True)
