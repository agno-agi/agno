"""
Culture Manager Metrics
=============================

When an agent uses a CultureManager, the culture model's
calls are tracked under the "culture_model" detail key.
"""

from agno.agent import Agent
from agno.culture.manager import CultureManager
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    culture_manager=CultureManager(model=OpenAIChat(id="gpt-4o-mini"), db=db),
    update_cultural_knowledge=True,
    db=db,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_response = agent.run(
        "Our team always does code reviews before merging. We pair program on complex features."
    )

    print("=" * 50)
    print("RUN METRICS")
    print("=" * 50)
    pprint(run_response.metrics)

    print("=" * 50)
    print("MODEL DETAILS")
    print("=" * 50)
    if run_response.metrics and run_response.metrics.details:
        for model_type, model_metrics_list in run_response.metrics.details.items():
            print(f"\n{model_type}:")
            for model_metric in model_metrics_list:
                pprint(model_metric)
