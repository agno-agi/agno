"""
Gemini Interactions - Antigravity multi-turn
=============================================

Continue an Antigravity interaction across turns. Each response carries an
interaction_id; the next turn references it via `previous_interaction_id`
so the API only receives the new user message. The server keeps the sandbox
state (files written, packages installed, browser history) attached to the
interaction chain - subsequent turns build on what the agent already did.

Persisting the interaction_id requires a db (e.g. SqliteDb): the assistant
message stores it under provider_data, and the next turn reads it back.

Note on `environment`: when continuing a chain, the existing sandbox is
already attached server-side. Re-sending `environment="remote"` is safe
(the API treats it as a hint that's reconciled against the running env);
if you want to be explicit, swap to the returned `env_<id>` after the
first turn to make the reuse intent unambiguous.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="antigravity-preview-05-2026",
        environment="remote",
    ),
    add_history_to_context=True,
    db=SqliteDb(db_file="tmp/data.db"),
    markdown=True,
)

if __name__ == "__main__":
    # Turn 1 - kick off the project. The agent provisions a sandbox, writes
    # files, and produces an initial artifact.
    agent.print_response(
        "Plot the growth of global solar energy generation over the last "
        "decade and save the plot as solar.png in the sandbox."
    )

    # Turn 2 - iterate on the artifact. The sandbox and solar.png are still
    # there from turn 1.
    agent.print_response(
        "Take solar.png and produce a 3-slide HTML deck that embeds it, "
        "with a title slide and a short takeaway per slide."
    )

    # Turn 3 - critique and revise. The agent can see the deck it just made.
    agent.print_response(
        "Review the deck for clarity and tighten the takeaways. Save the "
        "revised version as deck_v2.html."
    )
