"""
Step-Level User Input HITL Example (AgentOS)

This example demonstrates how to pause a workflow to collect user input
using Step parameters directly (without the @pause decorator).

This approach is useful when:
- Using agent-based steps that need user parameters
- You want to configure HITL at the Step level rather than on a function
- You need to override or add HITL to existing functions/agents

Use case: Collecting user preferences before an agent generates content.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, UserInputField
from agno.workflow.workflow import Workflow

from workflow_db import db


# Step 1: Gather context (no HITL)
def gather_context(step_input: StepInput) -> StepOutput:
    """Gather initial context from the input."""
    topic = step_input.input or "general topic"
    return StepOutput(
        content=f"Context gathered for: '{topic}'\n"
        "Ready to generate content based on user preferences."
    )


# Step 2: Content generator agent (HITL configured on Step, not function)
# Note: User input from HITL is automatically appended to the message as "User preferences:"
content_agent = Agent(
    name="Content Generator",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=[
        "You are a content generator.",
        "Generate content based on the topic and user preferences provided.",
        "The user preferences will be provided in the message - use them to guide your output.",
        "Respect the tone, length, and format specified by the user.",
        "Keep the output focused and professional.",
    ],
)


# Step 3: Format output (no HITL)
def format_output(step_input: StepInput) -> StepOutput:
    """Format the final output."""
    content = step_input.previous_step_content or "No content generated"
    return StepOutput(content=f"=== GENERATED CONTENT ===\n\n{content}\n\n=== END ===")


# Define workflow with Step-level HITL configuration
workflow = Workflow(
    name="content_generation_workflow",
    db=db,
    steps=[
        Step(name="gather_context", executor=gather_context),
        # HITL configured directly on the Step using agent
        Step(
            name="generate_content",
            step_id="generate_content123",
            agent=content_agent,
            requires_user_input=True,
            user_input_message="Please provide your content preferences:",
            user_input_schema=[
                UserInputField(
                    name="tone",
                    field_type="str",
                    description="Tone of the content: 'formal', 'casual', or 'technical'",
                    required=True,
                ),
                UserInputField(
                    name="length",
                    field_type="str",
                    description="Content length: 'short' (1 para), 'medium' (3 para), or 'long' (5+ para)",
                    required=True,
                ),
                UserInputField(
                    name="include_examples",
                    field_type="bool",
                    description="Include practical examples?",
                    required=False,
                ),
            ],
        ),
        Step(name="format_output", executor=format_output),
    ],
)
workflow.id = "user-input-02-step-user-input"


# Alternative: Using executor function with Step-level HITL
def process_data(step_input: StepInput) -> StepOutput:
    """Process data with user-specified options."""
    user_input = (
        step_input.additional_data.get("user_input", {})
        if step_input.additional_data
        else {}
    )

    format_type = user_input.get("format", "json")
    include_metadata = user_input.get("include_metadata", False)

    return StepOutput(
        content=f"Data processed with format: {format_type}, metadata: {include_metadata}"
    )


workflow_with_executor = Workflow(
    name="data_processing_workflow",
    db=db,
    steps=[
        Step(name="gather_context", executor=gather_context),
        # HITL on Step with a plain executor function
        Step(
            name="process_data",
            step_id="process_data123",
            executor=process_data,
            requires_user_input=True,
            user_input_message="Configure data processing:",
            user_input_schema=[
                UserInputField(
                    name="format",
                    field_type="str",
                    description="Output format: 'json', 'csv', or 'xml'",
                    required=True,
                ),
                UserInputField(
                    name="include_metadata",
                    field_type="bool",
                    description="Include metadata in output?",
                    required=False,
                ),
            ],
        ),
        Step(name="format_output", executor=format_output),
    ],
)
workflow_with_executor.id = "user-input-02-step-user-input-executor"


agent_os = AgentOS(
    description="Step-level user input HITL workflows",
    workflows=[workflow, workflow_with_executor],
    db=db,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="step_user_input:app", reload=True)
