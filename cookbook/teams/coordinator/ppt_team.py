from typing import Any, Dict, List

from agno import Agent, Team
from agno.models.openai import OpenAIChat
from agno.models.xai.xai import xAI
from agno.run.team import TeamRunResponse
from agno.tools.dalle import DalleTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.ppt import PowerPointTool
from pydantic import BaseModel


class PresentationSlide(BaseModel):
    title: str
    content: str
    facts: List[str]
    image_description: str
    image_path: str  # Added field to store the image path


researcher = Agent(
    name="Researcher",
    model=OpenAIChat("gpt-4o"),
    tools=[DuckDuckGoTools()],
    role="Finds credible sources and extracts key information.",
    instructions=[
        "Find credible sources for the given topic and summarize key findings.",
        "Extract essential facts, statistics, and relevant insights.",
        "Provide references for further reading.",
        "Ensure information is up-to-date and relevant.",
    ],
)

writer = Agent(
    name="Writer",
    model=OpenAIChat("gpt-4o"),
    tools=[DuckDuckGoTools()],
    role="Generates structured content for slides based on research.",
    instructions=[
        "Use clear and concise language suitable for presentations.",
        "Ensure each slide has a title, main content, and supporting facts as bullet points.",
        "Ensure smooth transitions between slides.",
        "Avoid unnecessary newlines or character-by-character spacing.",
        "Format the content properly to prevent text breaking in the slides.",
    ],
)


ppt_creator = Agent(
    name="PPT Creator",
    model=OpenAIChat("gpt-4o"),
    tools=[PowerPointTool()],
    role="Formats slides into a visually appealing PowerPoint presentation.",
    instructions=[
        "Structure slides with a logical flow.",
        "Ensure readability with appropriate font size and color contrast.",
        "Highlight key points visually without cluttering slides.",
        "Maintain a single PowerPoint file, appending new slides dynamically.",
        "Ensure each slide includes both text content and images before finalizing.",
        "Make the presentation slides beautiful by adding some colors, emojis and stuffs",
    ],
)

image_customizer = Agent(
    name="Image Customizer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    role="Generates custom images for each slide.",
    instructions=[
        "Create visually appealing images that match the slide content.",
        "Ensure images enhance comprehension and engagement.",
        "Maintain a consistent visual style across all slides.",
        "Return the link to each image crated with teh slide content",
    ],
)

ai_ppt_team = Team(
    name="AI PPT Team",
    mode="coordinator",
    model=OpenAIChat("gpt-4o"),
    members=[researcher, writer, image_customizer, ppt_creator],
    instructions=[
        "First, the researcher gathers detailed facts about the topic and shares them with the writer.",
        "Then, the writer generates structured slide content, including title, main points, and supporting facts.",
        "Next, the image customizer generates images for each slide and passes the image paths to the PPT creator. Pass the context from the writer and research agent to get the image",
        "Finally, the PPT creator formats the slides, integrating text and images into a cohesive PowerPoint file.",
        "Structure slides with a logical flow.",
        "Ensure readability with appropriate font size and color contrast.",
        "Highlight key points visually without cluttering slides.",
        "Collect all slides as a list of dictionaries ",
        """slides (List[Dict[str, Any]]): A list of slides, each containing:
                - "title" (str): Slide title.
                - "content" (List[str]): Bullet points for the slide.
                - "image_path" (str, optional): Path to an image to include.""",
        "Call PowerPointTool.create_ppt(slides=collected_slides, filename='presentation.pptx') to save the file.",
        "Ensure the PowerPoint file is saved in the working directory.",
    ],
    response_model=PresentationSlide,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

ai_ppt_team.print_response("Create a presentation on AI in Education")
