"""
This example demonstrates how multiple specialized agents coordinate to provide
comprehensive RAG responses with distributed reasoning capabilities. Each agent
has specific reasoning responsibilities to ensure thorough analysis.

Team Composition:
- Information Gatherer: Searches knowledge base and gathers raw information
- Reasoning Analyst: Applies logical reasoning to analyze gathered information
- Evidence Evaluator: Evaluates evidence quality and identifies gaps
- Response Coordinator: Synthesizes everything into a final reasoned response

Setup:
1. Run: `pip install agno anthropic cohere lancedb tantivy sqlalchemy`
2. Export your ANTHROPIC_API_KEY and CO_API_KEY
3. Run this script to see coordinated reasoning RAG in action
"""

from agno.agent import Agent
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.lancedb import LanceDb, SearchType

# Shared knowledge base for the reasoning team
knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs_reasoning_team",
        search_type=SearchType.hybrid,
        embedder=CohereEmbedder(id="embed-v4.0"),
        reranker=CohereReranker(model="rerank-v3.5"),
    ),
)

# Information Gatherer Agent - Specialized in comprehensive information retrieval
information_gatherer = Agent(
    name="Information Gatherer",
    model=Claude(id="claude-sonnet-4-20250514"),
    role="Gather comprehensive information from knowledge sources",
    knowledge=knowledge,
    search_knowledge=True,
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Search the knowledge base thoroughly for all relevant information.",
        "Use reasoning tools to plan your search strategy.",
        "Gather comprehensive context and supporting details.",
        "Document all sources and evidence found.",
    ],
    markdown=True,
)

# Reasoning Analyst Agent - Specialized in logical analysis
reasoning_analyst = Agent(
    name="Reasoning Analyst",
    model=Claude(id="claude-sonnet-4-20250514"),
    role="Apply logical reasoning to analyze gathered information",
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Analyze information using structured reasoning approaches.",
        "Identify logical connections and relationships.",
        "Apply deductive and inductive reasoning where appropriate.",
        "Break down complex topics into logical components.",
        "Use reasoning tools to structure your analysis.",
    ],
    markdown=True,
)

# Evidence Evaluator Agent - Specialized in evidence assessment
evidence_evaluator = Agent(
    name="Evidence Evaluator",
    model=Claude(id="claude-sonnet-4-20250514"),
    role="Evaluate evidence quality and identify information gaps",
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Evaluate the quality and reliability of gathered evidence.",
        "Identify gaps in information or reasoning.",
        "Assess the strength of logical connections.",
        "Highlight areas needing additional clarification.",
        "Use reasoning tools to structure your evaluation.",
    ],
    markdown=True,
)

# Response Coordinator Agent - Specialized in synthesis and coordination
response_coordinator = Agent(
    name="Response Coordinator",
    model=Claude(id="claude-sonnet-4-20250514"),
    role="Coordinate team findings into comprehensive reasoned response",
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Synthesize all team member contributions into a coherent response.",
        "Ensure logical flow and consistency across the response.",
        "Include proper citations and evidence references.",
        "Present reasoning chains clearly and transparently.",
        "Use reasoning tools to structure the final response.",
    ],
    markdown=True,
)

# Create coordinated reasoning RAG team
coordinated_reasoning_team = Team(
    name="Coordinated Reasoning RAG Team",
    model=Claude(id="claude-sonnet-4-20250514"),
    members=[
        information_gatherer,
        reasoning_analyst,
        evidence_evaluator,
        response_coordinator,
    ],
    instructions=[
        "Work together to provide comprehensive, well-reasoned responses.",
        "Information Gatherer: First search and gather all relevant information.",
        "Reasoning Analyst: Then apply structured reasoning to analyze the information.",
        "Evidence Evaluator: Evaluate the evidence quality and identify any gaps.",
        "Response Coordinator: Finally synthesize everything into a clear, reasoned response.",
        "All agents should use reasoning tools to structure their contributions.",
        "Show your reasoning process transparently in responses.",
    ],
    show_members_responses=True,
    markdown=True,
)


async def async_reasoning_demo():
    """Demonstrate async coordinated reasoning RAG with streaming."""
    print("🧠 Async Coordinated Reasoning RAG Team Demo")
    print("=" * 60)

    query = "What are Agents and how do they work with tools? Explain the reasoning behind their design."

    # Add documentation content
    await knowledge.add_contents_async(
        urls=["https://docs.agno.com/basics/agents/overview.md"]
    )

    # Run async with streaming and reasoning
    await coordinated_reasoning_team.aprint_response(
        query, stream=True, show_full_reasoning=True
    )


def sync_reasoning_demo():
    """Demonstrate sync coordinated reasoning RAG."""
    print("🧠 Coordinated Reasoning RAG Team Demo")
    print("=" * 50)

    query = "What are Agents and how do they work with tools? Explain the reasoning behind their design."

    # Add documentation content
    knowledge.add_contents(urls=["https://docs.agno.com/basics/agents/overview.md"])

    # Run with detailed reasoning output
    coordinated_reasoning_team.print_response(
        query, stream=True, show_full_reasoning=True
    )


if __name__ == "__main__":
    # Choose which demo to run
    # asyncio.run(async_reasoning_demo())

    sync_reasoning_demo()
