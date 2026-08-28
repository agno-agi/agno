"""
Database-Backed Skills with Save and Load
=========================================

Create a content-carrying skill directly in the skills table, give it to an
Agent through DbSkills, save the Agent, load it back, and prove the reloaded
skill still carries its content and its script still executes.

Prerequisites: none (the model is constructed but never invoked)
Run: .venvs/demo/bin/python cookbook/02_agents/16_skills/db_skills.py
Try: Rerun the file; the delete-first step makes it repeatable
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.skills import DbSkills, Skills

# ---------------------------------------------------------------------------
# Create the Database and the Skill Definition
# ---------------------------------------------------------------------------

AGENT_ID = "db-skills-agent"
SKILL_NAME = "unit-converter"
SCRIPT_NAME = "convert_units.py"

db = SqliteDb(db_file="tmp/skills_db_demo.db")

# A database skill carries its own file contents instead of a source_path:
# scripts maps each filename to its UTF-8 text, so nothing lives on disk.
SKILL_DEFINITION = {
    "name": SKILL_NAME,
    "description": "Convert kilometers to miles with a bundled script.",
    "instructions": (
        "To convert kilometers to miles, run the convert_units.py script with "
        "get_skill_script and execute=true, then read the JSON it prints."
    ),
    "scripts": {
        # Scripts execute directly on Unix, so the shebang picks the interpreter.
        SCRIPT_NAME: (
            "#!/usr/bin/env python3\n"
            "import json\n"
            "\n"
            "KM_TO_MILES = 0.621371\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    kilometers = 5.0\n"
            "    print(\n"
            "        json.dumps(\n"
            '            {"kilometers": kilometers, "miles": round(kilometers * KM_TO_MILES, 3)}\n'
            "        )\n"
            "    )\n"
        ),
    },
}


# ---------------------------------------------------------------------------
# Run the Save and Load Round Trip
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Delete-first keeps the run repeatable: create_skill refuses duplicates.
    db.delete_skill(SKILL_NAME)
    created = db.create_skill(SKILL_DEFINITION)
    print(f"Created skill {created['name']} (version {created['version']})")

    # Built after create_skill, not at module level: Skills loads eagerly at
    # construction, so the row must exist first or the loader finds nothing.
    agent = Agent(
        id=AGENT_ID,
        name="Unit Converter Agent",
        model=OpenAIResponses(id="gpt-5.6"),
        db=db,
        skills=Skills(loaders=[DbSkills(db, names=[SKILL_NAME])]),
        instructions=[
            "Use the unit-converter skill to answer distance conversion questions.",
        ],
    )

    version = agent.save()
    print(f"Saved agent {AGENT_ID} as config version {version}")

    loaded_agent = Agent.load(AGENT_ID, db=db)
    if loaded_agent is None:
        raise RuntimeError("Agent.load returned None")
    if loaded_agent.skills is None:
        raise RuntimeError("The loaded agent has no skills attached")

    loaded_names = loaded_agent.skills.get_skill_names()
    print(f"Loaded agent {AGENT_ID}; skills resolved from the database: {loaded_names}")
    if SKILL_NAME not in loaded_names:
        raise RuntimeError(
            f"Skill {SKILL_NAME} did not survive the save and load round trip"
        )

    loaded_skill = loaded_agent.skills.get_skill(SKILL_NAME)
    if loaded_skill is None or loaded_skill.source_type != "db":
        raise RuntimeError("The reloaded skill did not come from the skills table")
    if loaded_skill.script_contents != SKILL_DEFINITION["scripts"]:
        raise RuntimeError("The reloaded skill lost its script content")
    print(
        f"Skill {SKILL_NAME} present after load with source_type=db and matching content"
    )

    # The same call the model would make, made directly so the proof does not
    # depend on the model choosing to use the tool.
    script_tool = next(
        (
            tool
            for tool in loaded_agent.skills.get_tools()
            if tool.name == "get_skill_script"
        ),
        None,
    )
    if script_tool is None:
        raise RuntimeError("The loaded agent did not register get_skill_script")
    result = json.loads(
        script_tool.entrypoint(
            skill_name=SKILL_NAME, script_path=SCRIPT_NAME, execute=True
        )
    )
    if result.get("returncode") != 0:
        raise RuntimeError(f"Skill script failed: {result}")
    conversion = json.loads(result["stdout"])
    if conversion["miles"] != 3.107:
        raise RuntimeError(f"Unexpected conversion result: {conversion}")
    print(f"Skill script ran from database content: {conversion}")
