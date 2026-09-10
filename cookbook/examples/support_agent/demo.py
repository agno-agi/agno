"""Exercise supported answers, conversational retrieval, and a local handoff.
--fixture uses scripted model responses with real Agno retrieval and persistence.
"""

import sys
from pathlib import Path
from uuid import uuid4

from support_agent import SupportAnswer, agent

# ---------------------------------------------------------------------------
# Create one conversation: follow-ups need the same session and user
# ---------------------------------------------------------------------------
PROMPTS = [
    "How do I export a Lantern workspace?",
    "Can a member do that too?",
    "Can you guarantee my exported data stays in Germany under a custom contract?",
]

# ---------------------------------------------------------------------------
# Run the same support agent and save any handoff locally
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--fixture" in sys.argv:
        from fixture_model import fixture_model

        agent.model = fixture_model()
    session = str(uuid4())
    for question in PROMPTS:
        result = agent.run(question, user_id="support-demo", session_id=session)
        assert isinstance(result.content, SupportAnswer), result.status
        references = {
            doc["meta_data"]["source"]
            for group in result.references or []
            for doc in group.references or []
        }
        assert set(result.content.sources) <= references, "Unretrieved source cited"
        print(result.content.model_dump_json(indent=2))
        if result.content.handoff:
            output = Path("tmp") / f"handoff-{result.run_id}.json"
            output.parent.mkdir(exist_ok=True)
            output.write_text(result.content.handoff.model_dump_json(indent=2))
            print("Saved locally:", output)
