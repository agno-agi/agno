from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.db.sqlite import SqliteDb


db = SqliteDb(db_file="tmp/agents.db")

# ------------------------------------------------------------
# Create an agent and save the config to the DB
# ------------------------------------------------------------
agent = Agent(
    id="web-search-agent", # Adding the ID is highly recommended for finding the config in the DB
    name="Web Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,  # DB is required to save the agent's config
    tools=[DuckDuckGoTools()],
    instructions="You are a web search agent that can search the web for information.",
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
)

agent.print_response("What is the current price of NVIDIA?")

# Save the agent to the DB
agent.save(
    # version = "v1.0"  # Optional: Specify a custom version
)


# # ------------------------------------------------------------
# # Modify the agent and save the config to the DB
# # ------------------------------------------------------------

# # Change the agent
# agent.add_tool(HackerNewsTools())

# # Save the new agent in the DB (optionally specify a version)
# agent.save(version="v1.1")


# # ------------------------------------------------------------
# # Modify the config directly in the DB
# # ------------------------------------------------------------

# # Update the config in the DB
# agent_config = agent.to_dict()
# agent_config["enable_session_summaries"] = True
# agent.db.upsert_config(
#     entity_id=agent.id,
#     entity_type="agent",
#     version="v1.2",
#     config=agent_config,
#     notes="Enabled session summaries",
#     set_as_current=True, # Set the config as the current version for the agent
# )

# agent = agent.load()  # Loads the current version of the agent

# # ------------------------------------------------------------
# # Create a new agent instance and load the current version of the agent
# # ------------------------------------------------------------
# new_agent = Agent(id="web-search-agent", db=db).load( # Loads the current version of the agent
#     # version="v1.2" # Optional: Specify a specific version to load
# ) 

# new_agent.print_response("What is the current price of Apple?")


# # ------------------------------------------------------------
# # Reload the agent from config on each run
# # ------------------------------------------------------------
# agent = Agent(
#     id="web-search-agent", # Adding the ID is required to find the config in the DB
#     db=db,  # DB is required to save/load the agent's config
#     reload_on_run=True,  # Reload the config on each run (useful if you change the config in the background)
# )

# agent.print_response("What is the current price of NVIDIA?")


# # ------------------------------------------------------------
# # Reload the agent from config on each run
# # ------------------------------------------------------------
# agent = Agent(
#     id="web-search-agent", # Adding the ID is highly recommended for finding the config in the DB
#     db=db,  # DB is required to save the agent's config
# )

# # Specify the version to use for this run
# agent.print_response("What is the current price of NVIDIA?", version="v1.0")  