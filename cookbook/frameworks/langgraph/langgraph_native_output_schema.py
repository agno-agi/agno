"""
Native structured output with LangGraph: build a node with .with_structured_output()
so LangChain constrains the model, and point the agent's output_key at the state key
that holds the resulting object. The adapter returns it validated rather than parsing
it out of message text.

Pass output_schema on the run so the framework's typed output is validated end to end.

Requirements:
    pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python cookbook/frameworks/langgraph/langgraph_native_output_schema.py
"""

from typing import List

from agno.agents.langgraph import LangGraphAgent
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class MovieScript(BaseModel):
    title: str = Field(..., description="Title of the movie")
    genre: str = Field(..., description="Genre of the movie")
    characters: List[str] = Field(..., description="Names of the main characters")


class State(TypedDict):
    question: str
    script: MovieScript


# ----- .with_structured_output() turns on LangChain's native structured output;
#       the node writes the resulting object to the `script` state key -----
def write_script(state: State):
    llm = ChatOpenAI(model="gpt-5.5").with_structured_output(MovieScript)
    return {"script": llm.invoke(state["question"])}


graph = StateGraph(State)
graph.add_node("write_script", write_script)
graph.add_edge(START, "write_script")
compiled = graph.compile()


# ----- Point output_key at the state key holding the model instance -----
agent = LangGraphAgent(
    name="LangGraph Writer",
    graph=compiled,
    input_key="question",
    output_key="script",
)

response = agent.run("Write a movie script set in Tokyo.", output_schema=MovieScript)

# response.content is a MovieScript instance produced by LangGraph, not parsed from text
script = response.content
print("Title:", script.title)
print("Genre:", script.genre)
print("Characters:", ", ".join(script.characters))
