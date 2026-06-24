"""
Multimodal Workflow
===================

A parallel workflow that runs visual analysis and web research
simultaneously, then synthesizes findings with optional image
generation and PDF output — all delivered over WhatsApp.

Workflow structure:
  Parallel:
    - Visual Analysis (analyzes input images/files)
    - Web Research (searches for related context)
  Sequential:
    - Creative Synthesis (combines results, generates images/PDFs)

Requires:
  WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID
  OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.dalle import DalleTools
from agno.tools.file_generation import FileGenerationTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Parallel, Step, Workflow

analyst = Agent(
    name="Visual Analyst",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Analyze any images or files provided.",
        "Describe visual elements, composition, colors, mood.",
        "If no image, analyze the text topic visually.",
        "Keep analysis concise but detailed.",
    ],
    markdown=True,
)

researcher = Agent(
    name="Web Researcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    instructions=[
        "Search the web for information related to the user's request.",
        "Provide relevant facts, trends, and context.",
    ],
    markdown=True,
)

synthesizer = Agent(
    name="Creative Synthesizer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools(), FileGenerationTools()],
    instructions=[
        "Combine the analysis and research from previous steps.",
        "If the user asked for an image, generate one with DALL-E.",
        "If the user asked for a report or document, generate a PDF.",
        "Provide a final comprehensive response.",
    ],
    markdown=True,
)

analysis_step = Step(
    name="Visual Analysis",
    agent=analyst,
    description="Analyze input images/files or describe the topic visually",
)

research_step = Step(
    name="Web Research",
    agent=researcher,
    description="Search the web for related context and information",
)

research_phase = Parallel(
    analysis_step,
    research_step,
    name="Research Phase",
)

synthesis_step = Step(
    name="Creative Synthesis",
    agent=synthesizer,
    description="Combine analysis + research into a final response, generate images or PDFs if requested",
)

creative_workflow = Workflow(
    name="Creative Pipeline",
    steps=[research_phase, synthesis_step],
)

agent_os = AgentOS(
    workflows=[creative_workflow],
    interfaces=[Whatsapp(workflow=creative_workflow)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="multimodal_workflow:app", reload=True)
