"""Real local indexing and API contracts with deterministic model boundaries."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.base import Embedder
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType
from fastapi.testclient import TestClient


class FixtureEmbedder(Embedder):
    def get_embedding(self, text):
        return [1.0] + [
            float(word in text.lower())
            for word in (
                "schedule",
                "report",
                "team",
                "admin",
                "export",
                "csv",
                "filter",
            )
        ]

    def get_embedding_and_usage(self, text):
        return self.get_embedding(text), None

    async def async_get_embedding(self, text):
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding_and_usage(text)


class FixtureModel(Model):
    def __init__(self):
        super().__init__(id="fixture", name="Fixture", provider="local")
        self.turn = 0
        self.messages_seen = []

    def invoke(self, messages, **kwargs):
        self.messages_seen.append(messages)
        self.turn += 1
        if self.turn % 2:
            return ModelResponse(
                role="assistant",
                response_usage=MessageMetrics(),
                tool_calls=[
                    {
                        "id": f"search-{self.turn}",
                        "type": "function",
                        "function": {
                            "name": "search_knowledge_base",
                            "arguments": json.dumps(
                                {"query": "schedule weekly report Team admins"}
                            ),
                        },
                    }
                ],
            )
        return ModelResponse(
            role="assistant",
            response_usage=MessageMetrics(),
            content="The Team plan and workspace admins are required. Source: Product documentation.",
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response, **kwargs):
        return response


@pytest.fixture
def product(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "False")
    sys.modules.pop("product_agent", None)
    module = importlib.import_module("product_agent")
    module.knowledge.vector_db.embedder = FixtureEmbedder(dimensions=8)
    module.product_agent.model = FixtureModel()
    document = Path("product.md")
    document.write_text((Path(__file__).parent / "product.md").read_text())
    module.knowledge.insert(name="Product documentation", path=str(document))
    return module


def test_index_restart_and_document_update(product):
    restarted = ChromaDb(
        collection="product-docs",
        path="data/chromadb",
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=FixtureEmbedder(dimensions=8),
    )
    results = restarted.search("schedule a weekly report")
    assert results and any("Team plan" in doc.content for doc in results)
    document = Path("product.md")
    document.write_text(document.read_text().replace("Team plan", "Business plan"))
    product.knowledge.insert(name="Product documentation", path=str(document))
    updated = restarted.search("schedule a weekly report")
    assert any("Business plan" in doc.content for doc in updated)
    assert all("Team plan" not in doc.content for doc in updated)


def test_http_followup_references_and_persisted_session(product):
    with TestClient(product.app, base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200
        first = client.post(
            "/agents/product-agent/runs",
            data={
                "message": "How do I schedule a weekly report in Acme Reports?",
                "user_id": "demo-user",
                "session_id": "product-questions",
                "stream": "false",
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["session_id"] == "product-questions"
        second = client.post(
            "/agents/product-agent/runs",
            data={
                "message": "Which plan do I need for that, and who can configure it?",
                "user_id": "demo-user",
                "session_id": "product-questions",
                "stream": "false",
            },
        )
        assert second.status_code == 200, second.text
    assert any(
        "How do I schedule" in str(message.content)
        for message in product.product_agent.model.messages_seen[-1]
    )
    saved = SqliteDb(db_file="data/agents.db").get_session(
        session_id="product-questions", session_type=SessionType.AGENT
    )
    assert len(saved.runs) == 2
    for run in saved.runs:
        assert run.references
        assert any(
            "Team plan" in doc["content"]
            for group in run.references
            for doc in group.references
        )
