"""
Multi Context Provider — Streaming Demo
========================================

Tests streaming with MULTIPLE context providers. Each provider has its own
sub-agent, and when the parent agent calls them, all sub-agent events stream
through in real-time.

This exercises the most complex scenario: parallel sub-agent tool calls with
nested events from each.

Run locally:
    python cookbook/12_context/24_multi_context_streaming.py

Then open os.agno.com and ask: 'Compare our architecture wiki with our docs wiki'

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import shutil
from pathlib import Path

from agno.agent import Agent
from agno.context.wiki import FileSystemBackend, WikiContextProvider
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# Wiki 1: Architecture docs
ARCH_PATH = Path(__file__).resolve().parent / "demo-arch-wiki"
if ARCH_PATH.exists():
    shutil.rmtree(ARCH_PATH)
ARCH_PATH.mkdir()
(ARCH_PATH / "overview.md").write_text(
    "# Architecture Overview\n\n"
    "Our platform uses microservices:\n"
    "- **auth-service**: OAuth2 + JWT tokens\n"
    "- **api-gateway**: Kong with rate limiting\n"
    "- **user-service**: PostgreSQL backend\n"
    "- **notification-service**: Redis pub/sub\n"
)
(ARCH_PATH / "scaling.md").write_text(
    "# Scaling Strategy\n\n"
    "We scale horizontally with Kubernetes:\n"
    "1. HPA based on CPU/memory\n"
    "2. Pod disruption budgets for availability\n"
    "3. Node auto-scaling via cluster autoscaler\n"
)

# Wiki 2: Operations runbooks
OPS_PATH = Path(__file__).resolve().parent / "demo-ops-wiki"
if OPS_PATH.exists():
    shutil.rmtree(OPS_PATH)
OPS_PATH.mkdir()
(OPS_PATH / "oncall.md").write_text(
    "# On-Call Runbook\n\n"
    "When paged:\n"
    "1. Check Grafana dashboards\n"
    "2. Review recent deploys in ArgoCD\n"
    "3. Check error rates in Datadog\n"
    "4. Escalate to #incidents Slack channel\n"
)
(OPS_PATH / "deploys.md").write_text(
    "# Deployment Guide\n\n"
    "Standard deploy process:\n"
    "1. PR approved and merged to main\n"
    "2. CI builds and pushes to ECR\n"
    "3. ArgoCD syncs to staging\n"
    "4. Manual promotion to production\n"
)

# Create two context providers
arch_wiki = WikiContextProvider(
    id="arch",
    name="Architecture Wiki",
    backend=FileSystemBackend(path=ARCH_PATH),
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

ops_wiki = WikiContextProvider(
    id="ops",
    name="Operations Wiki",
    backend=FileSystemBackend(path=OPS_PATH),
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# Parent agent with BOTH context providers as tools
agent = Agent(
    name="Platform Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        *arch_wiki.get_tools(),
        *ops_wiki.get_tools(),
    ],
    instructions=[
        arch_wiki.instructions(),
        ops_wiki.instructions(),
        "You help users understand our platform. Use query_arch for architecture "
        "questions and query_ops for operations/runbook questions.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Multi-context provider streaming demo",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    print("\nArchitecture Wiki files:")
    for f in ARCH_PATH.iterdir():
        print(f"  - {f.name}")
    print("\nOperations Wiki files:")
    for f in OPS_PATH.iterdir():
        print(f"  - {f.name}")
    print()
    print("Starting AgentOS on http://localhost:7777")
    print("Connect via os.agno.com and try:")
    print("  - 'What microservices do we have?'")
    print("  - 'How do I handle an on-call page?'")
    print("  - 'Compare our architecture with our deployment process'")
    print()
    agent_os.serve(app="24_multi_context_streaming:app", reload=True)
