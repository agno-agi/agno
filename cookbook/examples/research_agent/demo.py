"""Save a research brief, checking that every citation was actually inspected.
Default fixture sources still use the live model. --fixture uses scripted model
responses for a completely offline, deterministic Agent/tool execution.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

from research_agent import MODE, ResearchBrief, agent

# ---------------------------------------------------------------------------
# Create the research request
# ---------------------------------------------------------------------------
QUESTION = "Should a small public library pilot a monthly repair cafe?"

# ---------------------------------------------------------------------------
# Run the same agent and persist a checked brief
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--fixture" in sys.argv:
        if MODE != "fixture":
            raise ValueError("--fixture requires RESEARCH_MODE=fixture")
        from fixture_model import fixture_model

        agent.model = fixture_model()
    result = agent.run(QUESTION, user_id="research-demo", session_id=str(uuid4()))
    assert isinstance(result.content, ResearchBrief), result.status
    inspected = set((result.session_state or {}).get("inspected", []))
    cited = {url for f in result.content.findings for url in f.sources}
    assert cited and cited <= inspected, "Brief contains an uninspected citation"
    artifact = {
        "mode": MODE,
        "model": "scripted fixture" if "--fixture" in sys.argv else "live model",
        "inspected_sources": sorted(inspected),
        "brief": result.content.model_dump(),
    }
    output = Path("tmp") / f"brief-{result.run_id}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2))
    print(output.read_text())
    print("Saved:", output)
