"""Router with CEL: route using nested additional_data fields.

Uses additional_data.config.output_format to select the
appropriate content formatter.

Requirements:
    pip install cel-python
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import CEL_AVAILABLE, Step, Workflow
from agno.workflow.router import Router

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

markdown_agent = Agent(
    name="Markdown Formatter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Format your response as clean Markdown with headers, lists, and code blocks.",
    markdown=True,
)

json_agent = Agent(
    name="JSON Formatter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Format your entire response as a valid JSON object with structured fields.",
    markdown=False,
)

plain_agent = Agent(
    name="Plain Text Formatter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Format your response as plain text with no special formatting.",
    markdown=False,
)

workflow = Workflow(
    name="CEL Nested Additional Data Router",
    steps=[
        Router(
            name="Format Router",
            selector=(
                'additional_data.config.output_format == "json" ? "JSON Formatter" : '
                'additional_data.config.output_format == "markdown" ? "Markdown Formatter" : '
                '"Plain Text Formatter"'
            ),
            choices=[
                Step(name="Markdown Formatter", agent=markdown_agent),
                Step(name="JSON Formatter", agent=json_agent),
                Step(name="Plain Text Formatter", agent=plain_agent),
            ],
        ),
    ],
)

if __name__ == "__main__":
    print("--- JSON format ---")
    workflow.print_response(
        input="List the top 3 programming languages.",
        additional_data={"config": {"output_format": "json"}},
    )
    print()

    print("--- Markdown format ---")
    workflow.print_response(
        input="List the top 3 programming languages.",
        additional_data={"config": {"output_format": "markdown"}},
    )
