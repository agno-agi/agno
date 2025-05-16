"""
🚀 Startup Idea Validator - Your Personal Business Validation Assistant!

This workflow helps entrepreneurs validate their startup ideas by:
1. Clarifying and refining the core business concept
2. Evaluating originality compared to existing solutions
3. Defining clear mission and objectives
4. Conducting comprehensive market research and analysis

Why is this helpful?
--------------------------------------------------------------------------------
• Get objective feedback on your startup idea before investing resources
• Understand your total addressable market and target segments
• Validate assumptions about market opportunity and competition
• Define clear mission and objectives to guide execution

Who should use this?
--------------------------------------------------------------------------------
• Entrepreneurs and Startup Founders
• Product Managers and Business Strategists
• Innovation Teams
• Angel Investors and VCs doing initial screening

Example use cases:
--------------------------------------------------------------------------------
• New product/service validation
• Market opportunity assessment
• Competitive analysis
• Business model validation
• Target customer segmentation
• Mission/vision refinement

Quick Start:
--------------------------------------------------------------------------------
1. Install dependencies:
   pip install openai agno

2. Set environment variables:
   - OPENAI_API_KEY

3. Run:
   python startup_idea_validator.py

The workflow will guide you through validating your startup idea with AI-powered
analysis and research. Use the insights to refine your concept and business plan!
"""

import json
from typing import Iterator, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.googlesearch import GoogleSearchTools
from agno.utils.log import logger
from agno.utils.pprint import pprint_run_response
from agno.workflow import RunEvent, RunResponse, Workflow
from pydantic import BaseModel, Field


class IdeaClarification(BaseModel):
    originality: str = Field(..., description="Originality of the idea.")
    mission: str = Field(..., description="Mission of the company.")
    objectives: str = Field(..., description="Objectives of the company.")


class MarketResearch(BaseModel):
    total_addressable_market: str = Field(
        ..., description="Total addressable market (TAM)."
    )
    serviceable_available_market: str = Field(
        ..., description="Serviceable available market (SAM)."
    )
    serviceable_obtainable_market: str = Field(
        ..., description="Serviceable obtainable market (SOM)."
    )
    target_customer_segments: str = Field(..., description="Target customer segments.")


class StartupIdeaValidator(Workflow):
    idea_clarifier_agent: Agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "Given a user's startup idea, its your goal to refine that idea. ",
            "Evaluates the originality of the idea by comparing it with existing concepts. ",
            "Define the mission and objectives of the startup.",
        ],
        add_history_to_messages=True,
        add_datetime_to_instructions=True,
        response_model=IdeaClarification,
        debug_mode=False,
    )

    market_research_agent: Agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[GoogleSearchTools()],
        instructions=[
            "You are provided with a startup idea and the company's mission and objectives. ",
            "Estimate the total addressable market (TAM), serviceable available market (SAM), and serviceable obtainable market (SOM). ",
            "Define target customer segments and their characteristics. ",
            "Search the web for resources if you need to.",
        ],
        add_history_to_messages=True,
        add_datetime_to_instructions=True,
        response_model=MarketResearch,
    )

    competitor_analysis_agent: Agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[GoogleSearchTools()],
        instructions=[
            "You are provided with a startup idea and some market research related to the idea. ",
            "Identify existing competitors in the market. ",
            "Perform Strengths, Weaknesses, Opportunities, and Threats (SWOT) analysis for each competitor. ",
            "Assess the startup’s potential positioning relative to competitors.",
        ],
        add_history_to_messages=True,
        add_datetime_to_instructions=True,
        markdown=True,
        debug_mode=False,
    )

    report_agent: Agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "You are provided with a startup idea and other data about the idea. ",
            "Summarise everything into a single report.",
        ],
        add_history_to_messages=True,
        add_datetime_to_instructions=True,
        markdown=True,
        debug_mode=False,
    )

    def get_idea_clarification(self, startup_idea: str) -> Optional[IdeaClarification]:
        try:
            response: RunResponse = self.idea_clarifier_agent.run(startup_idea)

            # Check if we got a valid response
            if not response or not response.content:
                logger.warning("Empty Idea Clarification response")
            # Check if the response is of the expected type
            if not isinstance(response.content, IdeaClarification):
                logger.warning("Invalid response type")

            return response.content

        except Exception as e:
            logger.warning(f"Failed: {str(e)}")

        return None

    def get_market_research(
        self, startup_idea: str, idea_clarification: IdeaClarification
    ) -> Optional[MarketResearch]:
        agent_input = {"startup_idea": startup_idea, **idea_clarification.model_dump()}

        try:
            response: RunResponse = self.market_research_agent.run(
                json.dumps(agent_input, indent=4)
            )

            # Check if we got a valid response
            if not response or not response.content:
                logger.warning("Empty Market Research response")

            # Check if the response is of the expected type
            if not isinstance(response.content, MarketResearch):
                logger.warning("Invalid response type")

            return response.content

        except Exception as e:
            logger.warning(f"Failed: {str(e)}")

        return None

    def get_competitor_analysis(
        self, startup_idea: str, market_research: MarketResearch
    ) -> Optional[str]:
        agent_input = {"startup_idea": startup_idea, **market_research.model_dump()}

        try:
            response: RunResponse = self.competitor_analysis_agent.run(
                json.dumps(agent_input, indent=4)
            )

            # Check if we got a valid response
            if not response or not response.content:
                logger.warning("Empty Competitor Analysis response")

            return response.content

        except Exception as e:
            logger.warning(f"Failed: {str(e)}")

        return None

    def run(self, startup_idea: str) -> Iterator[RunResponse]:
        logger.info(f"Generating a startup validation report for: {startup_idea}")

        # Clarify and quantify the idea
        idea_clarification: Optional[IdeaClarification] = self.get_idea_clarification(
            startup_idea
        )

        if idea_clarification is None:
            yield RunResponse(
                event=RunEvent.workflow_completed,
                content=f"Sorry, could not even clarify the idea: {startup_idea}",
            )
            return

        # Do some market research
        market_research: Optional[MarketResearch] = self.get_market_research(
            startup_idea, idea_clarification
        )

        if market_research is None:
            yield RunResponse(
                event=RunEvent.workflow_completed,
                content="Market research failed",
            )
            return

        competitor_analysis: Optional[str] = self.get_competitor_analysis(
            startup_idea, market_research
        )

        # Compile the final report
        final_response: RunResponse = self.report_agent.run(
            json.dumps(
                {
                    "startup_idea": startup_idea,
                    **idea_clarification.model_dump(),
                    **market_research.model_dump(),
                    "competitor_analysis_report": competitor_analysis,
                },
                indent=4,
            )
        )

        yield RunResponse(
            content=final_response.content, event=RunEvent.workflow_completed
        )


# Run the workflow if the script is executed directly
if __name__ == "__main__":
    from rich.prompt import Prompt

    # Get idea from user
    idea = Prompt.ask(
        "[bold]What is your startup idea?[/bold]\n✨",
        default="A marketplace for Christmas Ornaments made from leather",
    )

    # Convert the idea to a URL-safe string for use in session_id
    url_safe_idea = idea.lower().replace(" ", "-")

    startup_idea_validator = StartupIdeaValidator(
        description="Startup Idea Validator",
        session_id=f"validate-startup-idea-{url_safe_idea}",
        storage=SqliteStorage(
            table_name="validate_startup_ideas_workflow",
            db_file="tmp/agno_workflows.db",
        ),
    )

    final_report: Iterator[RunResponse] = startup_idea_validator.run(startup_idea=idea)

    pprint_run_response(final_report, markdown=True)
