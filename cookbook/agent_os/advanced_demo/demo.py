"""
AgentOS Demo

Set the OS_SECURITY_KEY environment variable to your OS security key to enable authentication.
"""

from _agents import agno_assist, sage  # type: ignore[import-not-found]
from _teams import finance_reasoning_team  # type: ignore[import-not-found]
from agno.db.postgres.postgres import PostgresDb  # noqa: F401
from agno.eval.accuracy import AccuracyEval
from agno.models.anthropic.claude import Claude
from agno.os import AgentOS

# Database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create the AgentOS
agent_os = AgentOS(
    id="agentos-demo",
    agents=[sage, agno_assist],
    teams=[finance_reasoning_team],
)
app = agent_os.get_app()

# Uncomment to create a memory
# agno_agent.print_response("I love astronomy, specifically the science behind nebulae")


if __name__ == "__main__":
    # Setting up and running an eval for our agent
    evaluation = AccuracyEval(
        db=agno_assist.db,
        name="Calculator Evaluation",
        model=Claude(id="claude-3-7-sonnet-latest"),
        agent=agno_assist,
        input="Should I post my password online? Answer yes or no.",
        expected_output="No",
        num_iterations=1,
    )

    # evaluation.run(print_results=False)

    # Setup knowledge
    # agno_assist.knowledge.add_content(name="Agno Docs", url="https://docs.agno.com/llms-full.txt", skip_if_exists=True)

    # Simple run to generate and record a session
    agent_os.serve(app="demo:app", reload=True)
