"""
Eval Cases
==========

Each case sends one input to one agent and (optionally) checks two things:

- **judge** — `AgentAsJudgeEval` scores the response against `criteria`
  (binary pass/fail) using an LLM.
- **reliability** — `ReliabilityEval` checks that the expected tool calls
  fired against `expected_tool_calls`.

Add a case below, then run `python -m evals`.
"""

from dataclasses import dataclass
from typing import Union

from agents.code_search import code_search
from agents.git_wiki import git_wiki
from agents.local_wiki import local_wiki
from agents.notion_wiki import notion_wiki
from agents.researcher import researcher
from agents.web_search import web_search
from agno.agent import Agent
from agno.team import Team
from agno.workflow import Workflow
from db import get_db
from teams.swarm import swarm

eval_db = get_db()


@dataclass(frozen=True)
class Case:
    """One eval case: an input to one agent/team/workflow + optional judge/reliability checks."""

    name: str
    agent: Union[Agent, Team, Workflow]
    input: str

    # LLM-judge rubric. Set `criteria` to enable.
    criteria: str | None = None

    # Tool-call assertion. Set `expected_tool_calls` to enable.
    expected_tool_calls: tuple[str, ...] | None = None
    allow_additional_tool_calls: bool = True


_BASE_CASES: tuple[Case, ...] = (
    # LocalWiki — read tool fires AND agent reports the wiki state honestly.
    Case(
        name="local_wiki_reports_state_honestly",
        agent=local_wiki,
        input="What does the wiki say about the Lindy Effect?",
        criteria=(
            "Either quotes a wiki page on the Lindy Effect, or honestly says the wiki "
            "does not have a page on it. Does NOT fabricate page content or invent URLs."
        ),
        expected_tool_calls=("query_local_wiki",),
    ),
    # WebSearch — search tool fires AND response cites a URL.
    Case(
        name="web_search_cites_url",
        agent=web_search,
        input="What is the latest stable release of CPython? Cite the source.",
        criteria=(
            "Answers with a specific CPython version and cites at least one real URL "
            "(python.org, peps.python.org, or another authoritative source). The response "
            "is grounded in fetched content, not refusal or hedging."
        ),
        expected_tool_calls=("query_web",),
    ),
    # CodeSearch — codebase tool fires AND response names the right agents.
    Case(
        name="code_search_lists_registered_agents",
        agent=code_search,
        input="Which agents are registered in this AgentOS demo (cookbook/01_demo)?",
        criteria=(
            "Identifies the demo agents (local-wiki, web-search, code-search, researcher; "
            "git-wiki and notion-wiki when env-gated). May reference cookbook/01_demo/run.py as the source."
        ),
        expected_tool_calls=("query_codebase",),
    ),
    # CodeSearch — graceful unknown.
    Case(
        name="code_search_admits_unknown_function",
        agent=code_search,
        input="Where is the function `fizz_buzz_xyz` defined in this project?",
        criteria=(
            "Honestly says the function `fizz_buzz_xyz` is not defined in this project. "
            "Does not fabricate a file path."
        ),
    ),
    # Researcher — composes web + wiki. Wiki check fires before (or alongside) web.
    Case(
        name="researcher_checks_wiki_then_web",
        agent=researcher,
        input="What is the latest stable release of CPython?",
        criteria=(
            "Answers with a specific CPython version and either cites a real URL "
            "(python.org, peps.python.org) or quotes a wiki page if one exists. The "
            "response is grounded in tool output, not guessing."
        ),
        expected_tool_calls=("query_local_wiki", "query_web"),
    ),
    # Swarm team — both models answer, leader synthesizes with disagreements + confidence.
    Case(
        name="swarm_synthesizes_two_models",
        agent=swarm,
        input="What is the latest stable release of CPython? Cite the source.",
        criteria=(
            "Answers with a specific CPython version. Includes a 'Confidence:' line "
            "(high/medium/low). If the two members disagreed, includes a 'Disagreement:' "
            "line; otherwise indicates agreement implicitly. Cites at least one URL."
        ),
    ),
)


# GitWiki case is only included when the agent is registered.
_GIT_WIKI_CASES: tuple[Case, ...] = (
    (
        Case(
            name="git_wiki_reports_state_honestly",
            agent=git_wiki,
            input="What does the wiki say about onboarding?",
            criteria=(
                "Either quotes an onboarding page from the wiki, or honestly says the "
                "wiki does not have one. Does NOT fabricate content."
            ),
            expected_tool_calls=("query_git_wiki",),
        ),
    )
    if git_wiki is not None
    else ()
)


# NotionWiki case is only included when the agent is registered.
_NOTION_WIKI_CASES: tuple[Case, ...] = (
    (
        Case(
            name="notion_wiki_reports_state_honestly",
            agent=notion_wiki,
            input="What does the wiki say about onboarding?",
            criteria=(
                "Either quotes an onboarding page from the wiki, or honestly says the "
                "wiki does not have one. Does NOT fabricate content."
            ),
            expected_tool_calls=("query_notion_wiki",),
        ),
    )
    if notion_wiki is not None
    else ()
)


CASES: tuple[Case, ...] = _BASE_CASES + _GIT_WIKI_CASES + _NOTION_WIKI_CASES
