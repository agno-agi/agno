import os
from dotenv import load_dotenv
from agno.os import AgentOS
from agno.workflow import Step, Workflow
from agents import search_orchestrator, evidence_extractor, report_synthesizer, db

# Load environment variables
load_dotenv()

# Create workflow steps
search_step = Step(
    name="Search",
    agent=search_orchestrator,
    description="Gather technical sources from web, GitHub, Wikipedia, and research papers",
)

extract_step = Step(
    name="Extract",
    agent=evidence_extractor,
    description="Extract key information and evidence from gathered sources",
)

synthesize_step = Step(
    name="Synthesize",
    agent=report_synthesizer,
    description="Synthesize findings into comprehensive research report",
)

# Create sequential workflow
research_workflow = Workflow(
    name="Deep Research Workflow",
    description="Comprehensive research workflow: Search → Extract → Synthesize",
    db=db,
    steps=[search_step, extract_step, synthesize_step],
)

# Create AgentOS
agent_os = AgentOS(
    os_id="deep-research-agent",
    description="AI-native deep research workflow for technical research and analysis",
    agents=[search_orchestrator, evidence_extractor, report_synthesizer],
    workflows=[research_workflow],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="main:app", reload=True)

