from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.db.sqlite import SqliteDb


db = SqliteDb(db_file="tmp/agents.db")

# Create a basic agent
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

agent.print_response("What is the current price of Tesla?")

# Save the agent's config in the DB
saved_config = agent.save_config()

# Change the agent
agent.add_tool(HackerNewsTools())

# Save the new config in the DB
saved_config = agent.save_config()

# Update the config in the DB
saved_config.config["enable_session_summaries"] = True
updated_config = agent.update_config(saved_config)

assert updated_config.config["enable_session_summaries"] == True

### Create a new agent from an existing config
new_agent = Agent.from_config(db=db, config_id=updated_config.id)

new_agent.print_response("What is the current price of NVIDIA?")


### Create a new agent from a config ID
new_new_agent = Agent(db=db, 
    config_id=updated_config.id,
    # run_from_config=True # Re-hydrate the agent on each run (optional)
)

new_new_agent.print_response("What is the current price of Apple?")
