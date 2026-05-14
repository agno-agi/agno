"""
Brief Workflow — research a topic and file it
==============================================

Two-step sequential pipeline:

  1. WebSearch     — gather and synthesize current info on the topic
  2. LocalWiki     — file the brief under `briefs/<date>-<slug>.md`

Use case: scheduler-friendly "every morning, brief me on X and put
it in the wiki". Set ``scheduler=True`` in ``run.py`` (already on)
and create a schedule via os.agno.com or the AgentOS API.

Workflows differ from Teams in that the step order is explicit and
the output of step N flows into step N+1.
"""

from agents.local_wiki import local_wiki
from agents.web_search import web_search
from agno.workflow import Step, Workflow
from db import get_db

research_step = Step(
    name="Research",
    description="Gather current information on the topic from the web.",
    agent=web_search,
)


file_step = Step(
    name="File to wiki",
    description=(
        "Take the research output from the previous step and file it as a "
        "new brief in the local wiki. Use the path `briefs/<YYYY-MM-DD>-<slug>.md`. "
        "Include a Source section listing every URL the research cited."
    ),
    agent=local_wiki,
)


brief = Workflow(
    id="brief",
    name="Brief",
    description="Research a topic on the web, then file the brief to the local wiki.",
    db=get_db(),
    steps=[research_step, file_step],
)
