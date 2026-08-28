"""
Structured output with a LangGraph agent, using a Pydantic schema.

The schema can be set on the agent, or passed per-run to override it.

Requirements:
    uv pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python cookbook/frameworks/langgraph/langgraph_output_schema.py
"""

from typing import List

from agno.agents.langgraph import LangGraphAgent
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState, StateGraph
from pydantic import BaseModel, Field


class MovieScript(BaseModel):
    title: str = Field(..., description="Title of the movie")
    genre: str = Field(..., description="Genre of the movie")
    characters: List[str] = Field(..., description="Names of the main characters")
    plot: str = Field(..., description="One paragraph plot summary")


class Haiku(BaseModel):
    lines: List[str] = Field(..., description="The three lines of the haiku")


# ----- Build a LangGraph agent -----
def chatbot(state: MessagesState):
    return {"messages": [ChatOpenAI(model="gpt-5.5").invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")
compiled = graph.compile()


# ----- Schema set on the agent -----
agent = LangGraphAgent(
    name="LangGraph Writer",
    graph=compiled,
    output_schema=MovieScript,
)

response = agent.run("Write a movie script set in Tokyo.")

# response.content is a MovieScript instance
script = response.content
print("Title:", script.title)
print("Genre:", script.genre)
print("Characters:", ", ".join(script.characters))
print("Plot:", script.plot)

# ----- Per-run schema overrides the agent-level one -----
response = agent.run("Write a haiku about Tokyo.", output_schema=Haiku)

haiku = response.content
print()
for line in haiku.lines:
    print(line)
