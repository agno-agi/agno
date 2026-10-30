"""
Save Skill to Database
======================

Demonstrates storing a skill as a versioned component, attaching it to an agent,
and loading the agent back with the exact skill version it was saved with.
"""

from pathlib import Path

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.skills import DbSkills, LocalSkills, Skill, SkillRef, Skills

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

skill_dir = (
    Path(__file__).parent.parent
    / "02_agents"
    / "16_skills"
    / "sample_skills"
    / "code-review"
)

# ---------------------------------------------------------------------------
# Run Skill Save Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Store the skill. Every save publishes a new version, scripts and references included.
    skill = LocalSkills(str(skill_dir)).load()[0]
    skill_version = skill.save(db=db)
    print(f"Saved skill '{skill.name}' as version {skill_version}")

    # Attach it to an agent. With no version, the agent uses the current one
    # and pins it when the agent is saved. Use version="latest" to follow new versions.
    agent = Agent(
        id="code-reviewer",
        name="Code Reviewer",
        model=OpenAIResponses(id="gpt-5.6-luna"),
        db=db,
        skills=Skills(loaders=[DbSkills(db, [SkillRef("code-review")])]),
    )
    agent_version = agent.save()
    print(f"Saved agent as version {agent_version}")
    print(
        f"Stored skill references: {db.get_config('code-reviewer')['config']['skills']}"
    )

    # Publishing a new skill version does not change the saved agent.
    skill.instructions += "\n\nAlways end the review with a one-line summary."
    print(f"Published skill version {skill.save(db=db)}")

    loaded = Agent.load(id="code-reviewer", db=db, strict=True)
    pinned = Skill.load("code-review", db=db, version=skill_version)
    print(
        f"Loaded agent uses the pinned skill: {loaded.skills.get_skill('code-review') == pinned}"
    )

    loaded.print_response(
        "Use your code-review skill to review this function:\n\ndef add(a, b):\n    return a - b",
        stream=True,
    )

    # A skill cannot be deleted while a saved agent references it.
    # agent.delete(hard_delete=True)
    # skill.delete(db=db)
