from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import File
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# Define agents
pdf_analyzer = Agent(
    name="PDF Analyzer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Analyze the provided image and extract key details, objects, and context.",
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Summarize the contents of the attached file in 1 paragraph.",
)

# Define steps
analysis_step = Step(
    name="PDF Analysis Step",
    agent=pdf_analyzer,
)

summarization_step = Step(
    name="Summarization Step",
    agent=summarizer,
)

# Create workflow with media input
media_workflow = Workflow(
    name="PDF Analysis and Research Workflow",
    description="Analyze a PDF and summarize the contents",
    steps=[analysis_step, summarization_step],
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflow.db",
    ),
)

# Run workflow with image input
if __name__ == "__main__":
    media_workflow.print_response(
        input="Please analyze this PDF and summarize the contents",
        files=[
            File(
                filepath="tests/path/to/your/file.pdf"  # <- put the actual path to the file
            )
        ],
        markdown=True,
        stream=True,
    )
