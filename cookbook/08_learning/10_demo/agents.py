"""
Learning Demo: Shared Agent
===========================
A single ops assistant with every database-backed learning store enabled:

- User Profile: structured fields (name, role, preferences)
- User Memory: unstructured observations about the user
- Session Context: goal, plan, and progress per session
- Entity Memory: facts, events, and relationships about external things
- Decision Log: significant decisions with reasoning

Learned Knowledge is left out because it requires a vector database.
See cookbook/08_learning/05_learned_knowledge for that store.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import (
    DecisionLogConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
)
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
db = SqliteDb(id="learning-demo-db", db_file="tmp/learning_demo.db")

# ---------------------------------------------------------------------------
# Learning Machine: all database-backed stores enabled
# ---------------------------------------------------------------------------
learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.5"),
    user_profile=True,
    user_memory=True,
    session_context=SessionContextConfig(enable_planning=True),
    entity_memory=True,
    decision_log=DecisionLogConfig(mode=LearningMode.AGENTIC),
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
ops_assistant = Agent(
    id="ops-assistant",
    name="Ops Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=learning,
    instructions=[
        "You are an engineering operations assistant.",
        "Keep answers short and practical.",
        "When you make a significant recommendation, record it with the log_decision tool, including your reasoning and the alternatives you considered.",
    ],
    markdown=True,
)
