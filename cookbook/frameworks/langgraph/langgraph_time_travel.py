"""
LangGraph time travel (replay & fork) through Agno's LangGraphAgent.

This demonstrates:
1. Running a multi-step LangGraph agent with checkpointing
2. Viewing state history
3. Replaying from a past checkpoint
4. Forking with modified state

Requirements:
    pip install langgraph langchain-openai

Usage:
    .venvs/demo/bin/python cookbook/frameworks/langgraph_time_travel.py
"""

from agno.agents.langgraph import LangGraphAgent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState, StateGraph

# ----- Build a LangGraph with checkpointer -----
llm = ChatOpenAI(model="gpt-5.4")


def chatbot(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}


graph = StateGraph(MessagesState)
graph.add_node("chatbot", chatbot)
graph.set_entry_point("chatbot")

# Compile WITH a checkpointer to enable time travel
checkpointer = MemorySaver()
compiled = graph.compile(checkpointer=checkpointer)

# ----- Wrap for Agno -----
agent = LangGraphAgent(
    name="Time Travel Agent",
    graph=compiled,
)

SESSION_ID = "demo-session"

# ----- Step 1: Run a conversation -----
print("=" * 60)
print("Step 1: Initial conversation")
print("=" * 60)
agent.print_response(
    "What is the capital of France?", stream=True, session_id=SESSION_ID
)

print("\n")
agent.print_response("And what about Germany?", stream=True, session_id=SESSION_ID)

# ----- Step 2: View state history -----
print("\n" + "=" * 60)
print("Step 2: State history")
print("=" * 60)
history = agent.get_state_history(SESSION_ID)
for i, snapshot in enumerate(history):
    print(
        f"  [{i}] next={snapshot.next}, checkpoint_id={snapshot.config['configurable']['checkpoint_id']}"
    )

# ----- Step 3: Replay from first checkpoint -----
print("\n" + "=" * 60)
print("Step 3: Replay from the first question")
print("=" * 60)
# History is reverse chronological, so the last entry with next=("chatbot",) is the first question
first_checkpoint = None
for snapshot in history:
    if snapshot.next == ("chatbot",):
        first_checkpoint = snapshot
# Use the first checkpoint found (most recent with next=chatbot)
if first_checkpoint:
    checkpoint_id = first_checkpoint.config["configurable"]["checkpoint_id"]
    print(f"  Replaying from checkpoint: {checkpoint_id}")
    agent.print_replay(SESSION_ID, checkpoint_id, stream=True)

# ----- Step 4: Fork with modified state -----
print("\n" + "=" * 60)
print("Step 4: Fork - ask about Italy instead")
print("=" * 60)
if first_checkpoint:
    from langchain_core.messages import HumanMessage

    checkpoint_id = first_checkpoint.config["configurable"]["checkpoint_id"]
    print(f"  Forking from checkpoint: {checkpoint_id}")
    agent.print_fork(
        SESSION_ID,
        checkpoint_id,
        values={"messages": [HumanMessage(content="What is the capital of Italy?")]},
        stream=True,
    )
