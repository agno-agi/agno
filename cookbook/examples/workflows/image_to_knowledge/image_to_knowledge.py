"""Image to Knowledge Workflow

A workflow that receives an image with metadata, extracts text using a multimodal agent,
and saves the extracted text to a file.

Supports two ways to provide the image:
1. URL: Provide image_url with a publicly accessible image URL
2. Base64: Provide image_base64 with base64-encoded image data

Requirements:
- OPENAI_API_KEY environment variable
"""

from pathlib import Path
from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field, model_validator


class ImageInput(BaseModel):
    """Structured input for the image to knowledge workflow.
    
    Provide either image_url OR image_base64 (not both).
    """

    image_url: Optional[str] = Field(default=None, description="URL of the image to process")
    image_base64: Optional[str] = Field(default=None, description="Base64-encoded image data")
    name: str = Field(description="Name identifier for the extracted content")
    description: str = Field(description="Description of the image content")
    metadata: dict = Field(default_factory=dict, description="Additional metadata about the image")

    @model_validator(mode="after")
    def validate_image_source(self):
        if not self.image_url and not self.image_base64:
            raise ValueError("Either image_url or image_base64 must be provided")
        if self.image_url and self.image_base64:
            raise ValueError("Provide either image_url or image_base64, not both")
        return self


# Agent for image to text extraction
image_to_text_agent = Agent(
    name="Image Text Extractor",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are an expert at extracting text and information from images.",
        "Analyze the provided image and extract all visible text.",
        "Also describe any relevant visual elements that provide context.",
        "Be thorough and accurate in your extraction.",
    ],
)


def extract_text_from_image(step_input: StepInput) -> StepOutput:
    """
    Custom function that extracts text from an image using the multimodal agent
    and saves it to a .txt file.
    """
    # Parse the structured input
    workflow_input = step_input.input
    if not isinstance(workflow_input, ImageInput):
        return StepOutput(
            content=f"Invalid input: Expected ImageInput schema, got {type(workflow_input)}",
            success=False,
        )

    name = workflow_input.name
    description = workflow_input.description
    metadata = workflow_input.metadata

    # Create Image object based on input type
    if workflow_input.image_url:
        image = Image(url=workflow_input.image_url)
        image_source = workflow_input.image_url
    else:
        image = Image(base64=workflow_input.image_base64)
        image_source = "base64-encoded"

    # Build the extraction prompt
    extraction_prompt = f"""
    Please extract all text from the following image.
    
    Image Description: {description}
    Additional Context: {metadata}
    
    Extract:
    1. All visible text in the image
    2. Any text that appears in signs, labels, or documents
    3. Contextual information that helps understand the text
    """

    try:
        # Run the agent with the image
        response = image_to_text_agent.run(
            extraction_prompt,
            images=[image],
        )

        extracted_text = response.content

        # Create output directory
        output_dir = Path("tmp/extracted_text")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save to .txt file
        output_file = output_dir / f"{name}.txt"
        file_content = f"""# Extracted Text from Image
Name: {name}
Description: {description}
Metadata: {metadata}
Image Source: {image_source}

---

{extracted_text}
"""
        output_file.write_text(file_content)

        result_content = f"""
## Text Extraction Complete

**Name:** {name}
**Output File:** {output_file}

### Extracted Content:
{extracted_text}
"""

        return StepOutput(content=result_content)

    except Exception as e:
        return StepOutput(
            content=f"Text extraction failed: {str(e)}",
            success=False,
        )


# Define the extraction step
extraction_step = Step(
    name="Image Text Extraction",
    description="Extract text from an image using a multimodal agent",
    executor=extract_text_from_image,
)

# Create the workflow
image_to_knowledge_workflow = Workflow(
    name="Image to Knowledge Workflow",
    description="Extract text from images and save to knowledge files",
    steps=[extraction_step],
    input_schema=ImageInput,
    db=SqliteDb(
        session_table="image_to_knowledge_session",
        db_file="tmp/image_to_knowledge.db",
    ),
)

# Initialize the AgentOS with the workflow
agent_os = AgentOS(
    description="Image to Knowledge extraction service",
    workflows=[image_to_knowledge_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="image_to_knowledge:app", reload=True)
