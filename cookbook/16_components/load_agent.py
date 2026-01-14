"""
This cookbook demonstrates how to load an agent from the database.

This is useful for loading a latest config of an Agent from the database.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    id="agno-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    name="Agno Agent",
    db=db,
)

# agent.print_response("How many people live in Canada?")

# Save the agent to the database
agent.save()

agent.load(agent_id="agno-agent", db=db, version=1)

agent.print_response("How many people live in Canada?")
