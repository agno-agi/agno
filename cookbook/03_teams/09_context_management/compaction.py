"""
Team Compaction
===============

Keeps a long team session inside the context window: older messages are replaced by
a generated summary and the recent turns are kept verbatim. It works exactly as it
does on an Agent - same settings, same guards, same archive.

It covers the team's own context - the leader's conversation, including what members
reported back. Members keep their own history and compact it through their own
`compaction` setting.

`compaction=True` folds when the provider rejects a request as too long. Pass a
`Compaction` object for a proactive threshold instead:

    compaction=Compaction(compact_at_tokens=100_000)

Either way `team.compact()` folds on demand, which is what this example uses: a short
demo reaches neither the provider's limit nor a threshold.
"""

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
itinerary_planner = Agent(
    name="Itinerary Planner",
    role="Plans day-by-day travel itineraries",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

budget_advisor = Agent(
    name="Budget Advisor",
    role="Estimates travel costs and keeps plans within budget",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
travel_team = Team(
    name="Travel Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[itinerary_planner, budget_advisor],
    db=SqliteDb(db_file="tmp/team_compaction.db"),
    session_id="team_compaction_demo",
    add_history_to_context=True,
    # uncompacted_runs is lowered so the fold below has history in front of the kept
    # tail to work with at demo scale.
    compaction=Compaction(uncompacted_runs=2),
    instructions="Keep answers short.",
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    questions = [
        "I am planning a trip to Japan in April. My budget is 4000 dollars.",
        "Which cities are best for cherry blossoms?",
        "How many days should I spend in Kyoto?",
        "What is a reasonable daily food budget there?",
        "Do I need a rail pass?",
    ]
    for question in questions:
        travel_team.print_response(question)

    # Fold now, rather than waiting for the context to reach compact_at_tokens.
    # Declining is a normal answer - a summary cannot pay for itself on a short
    # span - so check `compacted` and show `message` either way.
    result = travel_team.compact(session_id="team_compaction_demo")
    if result.compacted:
        r = result.record
        print(
            f"\n[compacted {r.messages_compacted} messages: "
            f"{r.tokens_before} -> {r.tokens_after} tokens, archived={r.archived}]"
        )
    else:
        print(f"\n[{result.status.value}] {result.message}")

    # The next run sends the summary in place of the folded turns. The budget was
    # stated in the first message, which has been folded - the summary carries it.
    run = travel_team.run("Remind me what my total budget was.")
    print(f"\n{run.content}")
