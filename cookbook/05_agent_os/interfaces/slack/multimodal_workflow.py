"""
Multimodal Workflow
===================

Tests streaming a workflow with multimodal input/output in Slack.

Capabilities tested:
  - Image INPUT:  Send an image, workflow processes it through steps
  - Image OUTPUT: DALL-E generates images during workflow steps
  - Parallel execution: Two steps run simultaneously
  - Sequential synthesis: Final step combines parallel results

Workflow structure:
  Parallel:
    - Visual Analysis (analyzes any input images/files)
    - Web Research (searches for related context)
  Sequential:
    - Creative Synthesis (generates a new image inspired by analysis + research)

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history,
             files:read, files:write
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools.dalle import DalleTools
from agno.tools.websearch import WebSearchTools
from agno.workflow import Parallel, Step, Workflow

# ---------------------------------------------------------------------------
# Step Agents
# ---------------------------------------------------------------------------

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
        "Format results with markdown.",
    ],
    markdown=True,
)

synthesizer = Agent(
    name="Creative Synthesizer",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    instructions=[
        "Combine the analysis and research from previous steps.",
        "If the user asked for an image, generate one with DALL-E.",
        "Provide a final comprehensive response.",
        "Format with markdown.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

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
    description="Combine analysis + research into a final response, generate images if requested",
)

creative_workflow = Workflow(
    name="Creative Pipeline",
    steps=[research_phase, synthesis_step],
)

# ---------------------------------------------------------------------------
# AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    workflows=[creative_workflow],
    interfaces=[
        Slack(
            workflow=creative_workflow,
            streaming=True,
            reply_to_mentions_only=True,
            suggested_prompts=[
                {
                    "title": "Analyze",
                    "message": "Send me an image to analyze and research",
                },
                {
                    "title": "Create",
                    "message": "Research cyberpunk art trends and generate an image",
                },
                {
                    "title": "Compare",
                    "message": "Compare impressionism and expressionism art styles",
                },
            ],
        )
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="multimodal_workflow:app", reload=True)
