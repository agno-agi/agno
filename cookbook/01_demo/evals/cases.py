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
from pathlib import Path

from agents.code_search import code_search
from agents.git_wiki import git_wiki
from agents.local_wiki import local_wiki
from agents.notion_wiki import notion_wiki
from agno.agent import Agent
from db import get_db

eval_db = get_db()

_ASSETS = Path(__file__).resolve().parents[1] / "assets"


@dataclass(frozen=True)
class Case:
    """One eval case: an input to one agent + optional judge/reliability checks."""

    name: str
    agent: Agent
    input: str

    # LLM-judge rubric. Set `criteria` to enable.
    criteria: str | None = None

    # Tool-call assertion. Set `expected_tool_calls` to enable.
    expected_tool_calls: tuple[str, ...] | None = None
    allow_additional_tool_calls: bool = True

    # Multimodal inputs (filepaths) attached to the agent run, if any.
    image_paths: tuple[str, ...] = ()
    audio_paths: tuple[str, ...] = ()


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
    # LocalWiki multimodal — read an attached image and file a page.
    Case(
        name="local_wiki_ingests_image",
        agent=local_wiki,
        input=(
            "Digest the attached diagram into a structured markdown page, "
            "then file it to the wiki under notes/."
        ),
        image_paths=(str(_ASSETS / "sample-diagram.png"),),
        criteria=(
            "Describes the content of the provided diagram in structured markdown "
            "(headings or bullets) and confirms it filed a wiki page. Does NOT claim "
            "it cannot see the image."
        ),
        expected_tool_calls=("update_local_wiki",),
    ),
    # CodeSearch — codebase tool fires AND response names the right agents.
    Case(
        name="code_search_lists_registered_agents",
        agent=code_search,
        input="Which agents are registered in this AgentOS demo (cookbook/01_demo)?",
        criteria=(
            "Identifies the demo agents (local-wiki, code-search; git-wiki and "
            "notion-wiki when env-gated). May reference cookbook/01_demo/run.py as the source."
        ),
        expected_tool_calls=("query_codebase",),
    ),
    # CodeSearch — graceful unknown.
    Case(
        name="code_search_admits_unknown_function",
        agent=code_search,
        input="Where is the function `fizz_buzz_xyz` defined in this project?",
        criteria=(
            "Says `fizz_buzz_xyz` is not actually defined or implemented in the project. "
            "Noting that the name only appears in an eval/test prompt string (e.g. this "
            "eval file) is acceptable and not a failure; it fails only if it invents a "
            "real definition site for the function."
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
