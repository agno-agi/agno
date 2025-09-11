from typing import Optional

from agno.agent import Agent
from agno.models.nebius import Nebius
from agno.tools.scrapegraph import ScrapeGraphTools
from agno.utils.log import logger
from agno.workflow import Workflow

# --- Agents Definition ---
searcher_agent = Agent(
    name="Research Searcher",
    tools=[ScrapeGraphTools()],
    model=Nebius(id="deepseek-ai/DeepSeek-V3-0324"),
    markdown=True,
    description=(
        "You are ResearchBot-X, an expert at finding and extracting high-quality, "
        "up-to-date information from the web. Your job is to gather comprehensive, "
        "reliable, and diverse sources on the given topic."
    ),
    instructions=(
        "1. Search for the most recent and authoritative sources on the topic\n"
        "2. Extract key facts, statistics, and expert opinions from multiple sources\n"
        "3. Cover different perspectives and highlight any disagreements or controversies\n"
        "4. Include relevant data points and expert insights where possible\n"
        "5. Organize findings in a clear, structured format\n"
        "6. Always mention the references and sources of the content\n"
        "7. Be comprehensive and detailed in your research\n"
        "8. Focus on credible sources like news sites, official docs, research papers"
    ),
)

analyst_agent = Agent(
    name="Research Analyst",
    model=Nebius(id="deepseek-ai/DeepSeek-V3-0324"),
    markdown=True,
    description=(
        "You are AnalystBot-X, a critical thinker who synthesizes research findings "
        "into actionable insights. Your job is to analyze, compare, and interpret the "
        "information provided by the researcher."
    ),
    instructions=(
        "1. Identify key themes, trends, and patterns in the research\n"
        "2. Highlight the most important findings and their implications\n"
        "3. Note any contradictions or areas of uncertainty\n"
        "4. Suggest areas for further investigation if gaps exist\n"
        "5. Present analysis in a structured, easy-to-read format\n"
        "6. Extract and list ONLY the reference links that were actually provided\n"
        "7. Do NOT create, invent, or hallucinate any links or sources\n"
        "8. If no references were provided, clearly state that\n"
        "9. Focus on actionable insights and practical implications"
    ),
)

writer_agent = Agent(
    name="Research Writer",
    model=Nebius(id="deepseek-ai/DeepSeek-V3-0324"),
    markdown=True,
    description=(
        "You are WriterBot-X, a professional technical writer. Your job is to craft "
        "a clear, engaging, and well-structured report based on the analyst's summary."
    ),
    instructions=(
        "1. Write an engaging introduction that sets the context\n"
        "2. Organize main findings into logical sections with clear headings\n"
        "3. Use bullet points, tables, or lists for clarity where appropriate\n"
        "4. Conclude with a summary and actionable recommendations\n"
        "5. Include a References section ONLY if actual links were provided\n"
        "6. Use ONLY the reference links that were explicitly provided by the analyst\n"
        "7. Format references as clickable markdown links when available\n"
        "8. Never add fake or made-up links - only use verified sources\n"
        "9. Ensure the report is professional, clear, and actionable"
    ),
)


# --- Main Execution Function ---
def deep_research_execution(
    session_state,
    topic: str = None,
) -> str:
    """
    Deep research workflow execution function.

    Args:
        session_state: The shared session state
        topic: Research topic
    """

    if not topic:
        return "❌ No research topic provided. Please specify a topic."

    logger.info(f"Running deep researcher workflow for topic: {topic}")

    # Step 1: Research
    logger.info("Starting research phase")
    research_content = searcher_agent.run(topic)

    if not research_content or not research_content.content:
        return f"❌ Failed to gather research information for topic: {topic}"

    # Step 2: Analysis
    logger.info("Starting analysis phase")
    analysis = analyst_agent.run(research_content.content)

    if not analysis or not analysis.content:
        return f"❌ Failed to analyze research findings for topic: {topic}"

    # Step 3: Report Writing
    logger.info("Starting report writing phase")
    report = writer_agent.run(analysis.content)

    if not report or not report.content:
        return f"❌ Failed to generate final report for topic: {topic}"

    logger.info("Deep research workflow completed successfully")
    return report.content


# --- Workflow Definition ---
def get_deep_researcher_workflow(
    model_id: str = "nebius:deepseek-ai/DeepSeek-V3-0324",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Workflow:
    """Get a Deep Researcher Workflow with multi-agent pipeline"""

    return Workflow(
        name="Deep Researcher",
        description="AI-powered research assistant with multi-agent workflow for comprehensive research, analysis, and report generation",
        steps=deep_research_execution,
        session_state={},
    )
