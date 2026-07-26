"""
Dakera Integration
==================

Demonstrates persistent cross-session memory for Agno agents using
Dakera — a self-hosted, decay-weighted vector memory server.

Unlike cloud memory providers (Mem0, Zep), Dakera runs entirely on your
infrastructure. Data never leaves your environment.

Prerequisites:
    # Start Dakera locally
    docker run -d -p 3300:3300 \\
        -e DAKERA_API_KEY=demo \\
        ghcr.io/dakera-ai/dakera:latest

    uv pip install agno dakera

Usage:
    DAKERA_API_KEY=demo python cookbook/11_memory/integrations/dakera_integration.py
"""

import os
from dataclasses import dataclass, field
from typing import Optional

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.pprint import pprint_run_response

try:
    import httpx as _httpx  # noqa: F401
except ImportError:
    raise ImportError(
        "httpx is not installed. Please install it using `uv pip install httpx`."
    )


# ---------------------------------------------------------------------------
# Dakera memory store — thin REST client
# ---------------------------------------------------------------------------


@dataclass
class DakeraMemoryStore:
    """Persistent memory store backed by a self-hosted Dakera server.

    Self-host via Docker:
        docker run -p 3300:3300 -e DAKERA_API_KEY=demo ghcr.io/dakera-ai/dakera:latest

    REST API:
        POST /v1/memories          — store a memory
        POST /v1/memories/search   — semantic recall (decay-weighted)
    """

    base_url: str = field(
        default_factory=lambda: os.getenv("DAKERA_URL", "http://localhost:3300")
    )
    api_key: str = field(default_factory=lambda: os.getenv("DAKERA_API_KEY", ""))
    namespace: str = "agno-agent"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def store(
        self, content: str, user_id: str = "default", session_id: str = "default"
    ) -> None:
        """Persist a memory entry to Dakera."""
        httpx.post(
            f"{self.base_url}/v1/memories",
            headers=self._headers(),
            json={
                "content": content,
                "agent_id": self.namespace,
                "session_id": session_id,
                "metadata": {"user_id": user_id},
            },
            timeout=10.0,
        ).raise_for_status()

    def recall(
        self, query: str, user_id: Optional[str] = None, top_k: int = 5
    ) -> list[str]:
        """Recall memories semantically relevant to the query.

        Dakera uses decay-weighted scoring: memories that are recent and
        frequently accessed rank higher than stale, infrequently accessed ones.
        """
        payload: dict = {"query": query, "agent_id": self.namespace, "top_k": top_k}
        if user_id:
            payload["filter"] = {"metadata.user_id": user_id}
        resp = httpx.post(
            f"{self.base_url}/v1/memories/search",
            headers=self._headers(),
            json=payload,
            timeout=10.0,
        )
        resp.raise_for_status()
        return [r["content"] for r in resp.json().get("results", [])]


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

memory = DakeraMemoryStore()
user_id = "agno-demo"

# Store some initial memories — comment out after first run
initial_facts = [
    "The user's name is Alice Chen.",
    "Alice is a senior ML engineer at a fintech startup.",
    "Alice prefers Python over Julia for ML work.",
    "Alice is currently building a fraud detection pipeline using transformer models.",
]

print("Storing initial memories to Dakera...")
for fact in initial_facts:
    memory.store(fact, user_id=user_id, session_id="onboarding")
print(f"Stored {len(initial_facts)} memories.\n")


# ---------------------------------------------------------------------------
# Build agent with recalled context
# ---------------------------------------------------------------------------


def build_agent_with_memory(task: str) -> Agent:
    """Build an Agno agent with prior memories injected into the system prompt."""
    recalled = memory.recall(task, user_id=user_id, top_k=5)
    memory_context = (
        "Relevant memories about this user:\n" + "\n".join(f"- {m}" for m in recalled)
        if recalled
        else "No prior memories for this user."
    )
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        description="You are a helpful AI assistant with persistent memory about the user.",
        instructions=memory_context,
    )


# ---------------------------------------------------------------------------
# Session 1: initial query
# ---------------------------------------------------------------------------

task1 = "What kind of ML projects is the user working on?"
agent1 = build_agent_with_memory(task1)

print("=== Session 1: Initial query ===")
response1 = agent1.run(task1, stream=False)
pprint_run_response(response1)

# Store the exchange for future sessions
memory.store(
    f"Q: {task1}\nA: {response1.content}",
    user_id=user_id,
    session_id="session-1",
)

# ---------------------------------------------------------------------------
# Session 2: follow-up (simulates a new session / process restart)
# ---------------------------------------------------------------------------

task2 = "Recommend a specific transformer architecture for the user's current project."
agent2 = build_agent_with_memory(task2)

print("\n=== Session 2: Follow-up with recalled context ===")
response2 = agent2.run(task2, stream=False)
pprint_run_response(response2)

# The agent answers with full context from Session 1 — even after restart
# because memories live in Dakera, not in-process.
