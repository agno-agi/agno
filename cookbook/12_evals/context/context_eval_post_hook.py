"""ContextEval with full agent features - knowledge, memory, tools.

Demonstrates ContextEval evaluating an agent with:
- Knowledge base (PDF recipes)
- User memories
- Session summaries
- Tools (web search)
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.context import ContextEval, ContextEvaluation
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.lancedb import LanceDb, SearchType


def on_context_fail(evaluation: ContextEvaluation):
    """Callback triggered when evaluation score falls below threshold."""
    print("\n[CONTEXT EVAL FAILED]")
    print(f"Score: {evaluation.score}/10 (threshold: 7)")
    print(f"Reason: {evaluation.reason}")
    for aspect, score in evaluation.aspect_scores.items():
        if score < 7:
            print(f"  - {aspect}: {score}/10")


# Database for sessions, memories, and eval results
db = SqliteDb(db_file="tmp/context_eval_full.db")

# Knowledge base with Thai recipes
knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb_context_eval",
        table_name="recipe_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

# Context eval as post-hook
context_eval = ContextEval(
    name="Thai Chef Evaluation",
    model=OpenAIChat(id="gpt-5-mini"),
    threshold=7,
    on_fail=on_context_fail,
    print_results=True,
    print_summary=True,
    db=db,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a passionate Thai cuisine expert and cooking instructor.",
    role="Thai Chef Assistant",
    instructions=dedent("""\
        - Use the knowledge base references for authentic Thai recipes
        - Use web search only when knowledge base lacks information
        - Start responses with a cooking emoji
        - Include ingredient lists and numbered steps for recipes
        - Share cultural context and pro tips
        - End with an encouraging sign-off in Thai
        - Remember user preferences and dietary restrictions
    """),
    knowledge=knowledge,
    add_knowledge_to_context=True,  # Knowledge added to context for evaluation
    tools=[DuckDuckGoTools()],
    user_id="chef_user",
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    post_hooks=[context_eval],
    db=db,
    markdown=True,
)

print("Query 1: Recipe request")
response = agent.run("How do I make Pad Thai?")
print(response.content)

print("\nQuery 2: With user preference")
response = agent.run("I am vegetarian. What Thai dishes can I make?")
print(response.content)

print("\nQuery 3: Follow-up using memory")
response = agent.run("Based on my diet, which curry would you recommend?")
print(response.content)

print("\nQuery 4: Web search for modern info")
response = agent.run("What are the trending Thai restaurants in NYC right now?")
print(response.content)
