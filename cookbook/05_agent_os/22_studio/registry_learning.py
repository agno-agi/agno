"""
Wire Studio-built components to a Registry LearningMachine
==========================================================

Learning is the only memory surface a Studio-built component can be given,
and the deployer decides what learning exists: every LearningMachine a built
component may use is declared on the Registry, by name. The builder discovers
them with list_learning, picks one by namespace, and wires it with
learning_name. The stored config carries a reference to the name, never the
machine's own config, so a component can never author learning the deployer
did not declare. At dispatch the Registry supplies the live machine and the
framework injects the component's db and model into it.

This example declares two machines with different namespaces, lists them,
builds a published agent against one, shows the stored reference, rehydrates
the agent the way AgentOS does, and runs it as a user so the learning tools
mount. The build and rehydrate sections need no provider key; the run does.

Prerequisites: OPENAI_API_KEY (for the final run only)
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_learning.py
Try: wire learning_name="research-brain" and compare the namespaces the two agents write into
"""

import json
import os
from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine
from agno.learn.config import LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIResponses
from agno.os.utils import get_agent_by_id
from agno.registry import Registry
from agno.tools.studio import StudioTools

# ---------------------------------------------------------------------------
# Declare the learning machines on the Registry
# ---------------------------------------------------------------------------

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)
DB_FILE = DB_DIR / "registry_learning.db"
DB_FILE.unlink(missing_ok=True)

db = SqliteDb(id="registry-learning-db", db_file=str(DB_FILE))
model = OpenAIResponses(id="gpt-5.5")

# A registry machine is shared by every component that references it, and the
# framework injects a component's db and model into it only when the machine
# has none. Declare the model here so the deployer, not the first component
# that happens to run, decides what the shared brain captures with.
shared_brain = LearningMachine(
    name="shared-brain",
    namespace="shared",
    model=model,
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    entity_memory=True,
)
research_brain = LearningMachine(
    name="research-brain",
    namespace="research",
    model=model,
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    entity_memory=True,
)

registry = Registry(
    name="Learning Registry",
    models=[model],
    dbs=[db],
    learning=[shared_brain, research_brain],
)

studio = StudioTools(registry=registry, db=db, default_model_id="gpt-5.5")

# ---------------------------------------------------------------------------
# Discover what is declared, namespace first
# ---------------------------------------------------------------------------

print("--- list_learning ---")
listing = json.loads(studio.list_learning())
for row in listing["data"]["learning"]:
    print(
        f"{row['name']}: namespace={row['namespace']} model={row['model_id']} stores={row['stores']}"
    )

# ---------------------------------------------------------------------------
# Build against one machine; the stored config is a reference
# ---------------------------------------------------------------------------

print("--- create_agent(learning_name='shared-brain') ---")
created = json.loads(
    studio.create_agent(
        name="Profile Coach",
        component_id="profile-coach",
        instructions="Remember what the user tells you about themselves and use it in later answers.",
        model_id="gpt-5.5",
        learning_name="shared-brain",
        publish=True,
    )
)
print(json.dumps(created["data"], indent=2))

stored = db.get_config(component_id="profile-coach", version=1)["config"]
print("stored learning key:", stored["learning"])

print("--- get_component view ---")
view = json.loads(studio.get_component("profile-coach"))["data"]
print("learning_name:", view.get("learning_name"))

print("--- an undeclared name is refused ---")
refused = json.loads(
    studio.create_agent(name="Rogue", instructions="x", learning_name="my-own-brain")
)
print(refused["error"]["code"], "-", refused["error"]["message"])

# ---------------------------------------------------------------------------
# Rehydrate the way AgentOS does: same machine, db injected, model as declared
# ---------------------------------------------------------------------------

print("--- rehydrate ---")
agent = get_agent_by_id("profile-coach", agents=None, db=db, registry=registry)
print("agent.learning is shared_brain:", agent.learning is shared_brain)
agent.initialize_agent()
print(
    "machine db:",
    type(shared_brain.db).__name__,
    "model:",
    shared_brain.model.id if shared_brain.model else None,
)
tool_names = sorted(
    t.__name__ for t in shared_brain.get_tools(user_id="ash", agent_id=agent.id)
)
print("learning tools for user 'ash':", tool_names)
print(
    "learning tools with no user:",
    [t.__name__ for t in shared_brain.get_tools(user_id=None, agent_id=agent.id)],
)

# ---------------------------------------------------------------------------
# Run as a user so the learning tools are live
# ---------------------------------------------------------------------------

if os.getenv("OPENAI_API_KEY"):
    print("--- run as user 'ash' ---")
    response = agent.run(
        "My name is Ash and I prefer short, direct answers.", user_id="ash"
    )
    print(response.content)
else:
    print("--- run skipped: set OPENAI_API_KEY to run the agent as user 'ash' ---")

# ---------------------------------------------------------------------------
# Zero-config: the default machine, no Registry declaration needed
# ---------------------------------------------------------------------------

print("--- create_agent(enable_learning=True) ---")
created = json.loads(
    studio.create_agent(
        name="Note Taker",
        component_id="note-taker",
        instructions="Remember the user's preferences.",
        model_id="gpt-5.5",
        enable_learning=True,
        publish=True,
    )
)
print(
    "stored learning key:",
    db.get_config(component_id="note-taker", version=1)["config"]["learning"],
)
note_taker = get_agent_by_id("note-taker", agents=None, db=db, registry=registry)
note_taker.initialize_agent()
machine = note_taker.learning_machine
print(
    "default machine:",
    "user_profile" if machine.user_profile else "",
    "user_memory" if machine.user_memory else "",
    "model:",
    machine.model.id if machine.model else None,
)

# ---------------------------------------------------------------------------
# Detach with an empty string
# ---------------------------------------------------------------------------

print("--- edit_agent(learning_name='') ---")
edited = json.loads(studio.edit_agent("profile-coach", learning_name="", publish=True))
version = edited["data"]["version"]
print(
    "stored learning key after detach:",
    db.get_config(component_id="profile-coach", version=version)["config"].get(
        "learning"
    ),
)
