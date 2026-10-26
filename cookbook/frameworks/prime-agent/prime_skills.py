"""Load an explicit local skill while disabling automatic skill discovery.

The fixture's response marker appears only in its body. This checks observable
instruction loading, without installing a package or registering Agno tools.
"""

from os import getenv
from pathlib import Path

from agno.agents.prime import PrimeAgent

SKILL_PATH = Path(__file__).resolve().parent / "fixtures" / "skills" / "cookbook-report"
agent = PrimeAgent(
    name="Prime Skills",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    skills=[str(SKILL_PATH)],
    no_skills=True,
    ephemeral=True,
    timeout=120,
)

if __name__ == "__main__":
    run = agent.print_response(
        "Load the cookbook-report skill and follow its response format. Do not modify files.",
        stream=True,
    )
    assert str(run.content).strip() == "PRIME_SKILL_LOADED", run.content
    print("PASS: followed the explicitly configured skill")
