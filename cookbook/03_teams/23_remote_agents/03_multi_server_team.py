"""
Multi-Server Distributed Team
=============================

This cookbook demonstrates a team that spans multiple remote servers,
creating a truly distributed agent architecture.

Each RemoteAgent can point to a different server, enabling:
- Geographic distribution (agents in different regions)
- Specialized servers (GPU server for ML, high-memory for RAG)
- Separation of concerns (auth server, data server, etc.)
"""

import asyncio

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.team.team import Team


async def main():
    # 1. Local coordinator agent
    coordinator = Agent(
        name="Coordinator",
        model=OpenAIResponses(id="gpt-4o-mini"),
        instructions="You coordinate tasks and synthesize results from multiple sources.",
    )

    # 2. Remote agent on Server A (e.g., code analysis server)
    code_analyzer = RemoteAgent(
        base_url="http://server-a.example.com:7777",
        agent_id="code-analyzer",
        timeout=60.0,
    )

    # 3. Remote agent on Server B (e.g., documentation server)
    doc_searcher = RemoteAgent(
        base_url="http://server-b.example.com:7777",
        agent_id="doc-searcher",
        timeout=60.0,
    )

    # 4. Remote agent on Server C (e.g., ML inference server)
    ml_classifier = RemoteAgent(
        base_url="http://server-c.example.com:7777",
        agent_id="ml-classifier",
        timeout=120.0,  # Longer timeout for ML tasks
    )

    # 5. Create a distributed team
    team = Team(
        name="Distributed Analysis Team",
        model=OpenAIResponses(id="gpt-4o-mini"),
        members=[coordinator, code_analyzer, doc_searcher, ml_classifier],
        instructions="""\
You lead a distributed team of specialized agents:

- Coordinator: Synthesizes findings from all agents
- Code Analyzer: Analyzes code structure and patterns (Server A)
- Doc Searcher: Searches documentation and README files (Server B)
- ML Classifier: Classifies and categorizes using ML models (Server C)

For complex tasks, delegate to multiple agents in parallel when possible.""",
        show_members_responses=True,
    )

    print("Testing multi-server distributed team...")
    print("=" * 60)

    await team.aprint_response(
        "Analyze this repository: have Code Analyzer examine the structure, "
        "Doc Searcher find relevant documentation, and ML Classifier categorize "
        "the project type. Coordinator should synthesize all findings.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
