"""
Loop Through Team Lead and Member Metrics
=========================================

Shows how to walk the metrics surface on a TeamRunOutput.

Key thing to know:
  - run_output.metrics holds the team LEADER's calls only
    (model + parser_model + output_model + followup_model, plus background
    memory/learning models). It does NOT include member token usage.
  - Each member's metrics live on run_output.member_responses[i].metrics.
  - For nested teams, walk member_responses recursively.
  - For session-wide totals across runs, use team.get_session_metrics().
"""

from os import getenv
from typing import Iterable, Optional, Union

from agno.agent import Agent
from agno.metrics import RunMetrics
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import Team
from rich.pretty import pprint

endpoint = getenv("AZURE_OPENAI_ENDPOINT")
api_key = getenv("AZURE_OPENAI_API_KEY")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def print_run_metrics(label: str, metrics: Optional[RunMetrics]) -> None:
    if metrics is None:
        print(f"{label}: <no metrics>")
        return
    print(
        f"{label}: input={metrics.input_tokens}, "
        f"output={metrics.output_tokens}, total={metrics.total_tokens}"
    )
    if metrics.details:
        for model_type, entries in metrics.details.items():
            for entry in entries:
                print(
                    f"  - [{model_type}] {entry.provider}/{entry.id}: "
                    f"input={entry.input_tokens}, output={entry.output_tokens}, "
                    f"total={entry.total_tokens}"
                )


def walk_member_metrics(
    member_responses: Iterable[Union[RunOutput, TeamRunOutput]],
    depth: int = 1,
) -> None:
    """Recursive walker that prints metrics for every member (and sub-members)."""
    for i, mr in enumerate(member_responses):
        kind = "team" if isinstance(mr, TeamRunOutput) else "agent"
        name = mr.team_name if isinstance(mr, TeamRunOutput) else mr.agent_name
        prefix = "  " * depth
        print_run_metrics(f"{prefix}member[{i}] ({kind}: {name})", mr.metrics)
        if isinstance(mr, TeamRunOutput) and mr.member_responses:
            walk_member_metrics(mr.member_responses, depth + 1)


def total_run_tokens(run_output: TeamRunOutput) -> int:
    """Sum tokens across the leader and every member, recursively."""

    def walk(responses: Iterable[Union[RunOutput, TeamRunOutput]]) -> int:
        s = 0
        for mr in responses:
            if mr.metrics is not None:
                s += mr.metrics.total_tokens
            if isinstance(mr, TeamRunOutput) and mr.member_responses:
                s += walk(mr.member_responses)
        return s

    leader_total = run_output.metrics.total_tokens if run_output.metrics else 0
    return leader_total + walk(run_output.member_responses)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(base_url=endpoint, api_key=api_key, id="gpt-5-chat"),
    role="Answers factual questions concisely.",
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIChat(base_url=endpoint, api_key=api_key, id="gpt-5-chat"),
    role="Summarizes content into a single sentence.",
)

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
team = Team(
    name="Research Team",
    model=OpenAIChat(base_url=endpoint, api_key=api_key, id="gpt-5-chat"),
    members=[researcher, summarizer],
    delegate_to_all_members=True,
    store_member_responses=True,
)


if __name__ == "__main__":
    run_output = team.run(
        "Give me one interesting fact about the Apollo program, then summarize it in one sentence."
    )

    print("=" * 60)
    print("TEAM LEADER METRICS  (run_output.metrics)")
    print("Leader-only. Members are NOT included here.")
    print("=" * 60)
    print_run_metrics("leader", run_output.metrics)

    print()
    print("=" * 60)
    print("MEMBER METRICS  (run_output.member_responses[i].metrics)")
    print("=" * 60)
    walk_member_metrics(run_output.member_responses)

    print()
    print("=" * 60)
    print("FULL RUN TOTAL  (leader + all members, recursively)")
    print("=" * 60)
    print(f"total_tokens = {total_run_tokens(run_output)}")

    print()
    print("=" * 60)
    print("RAW RunMetrics OBJECTS")
    print("=" * 60)
    print("\n-- leader --")
    pprint(run_output.metrics)
    for i, mr in enumerate(run_output.member_responses):
        print(f"\n-- member[{i}] ({mr.__class__.__name__}) --")
        pprint(mr.metrics)
