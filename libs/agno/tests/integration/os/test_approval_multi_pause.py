"""AgentOS: each approval-required tool call in a run gets its own approval record.

Drives the documented database-resolution flow over HTTP: list the run's
pending approvals, resolve them, continue the run by id with empty tools. A
run that pauses a second time for a new call must surface a new pending
record for that call, and the call must not execute until it is approved.

The model is scripted so the flow is deterministic and needs no API key.
"""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.approval import approval
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

PAID: List[str] = []


class InvoiceScriptedModel(Model):
    """Pays INV-1, then INV-2 (one call per turn), then answers. Stateless:
    the next turn is derived from the tool results since the last user message."""

    def __init__(self):
        super().__init__(id="invoice-scripted", name="invoice-scripted", provider="test")

    def _next(self, messages: List[Any]) -> ModelResponse:
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        answered = sum(1 for m in messages[last_user + 1 :] if m.role == "tool")
        if answered < 2:
            r = ModelResponse(role="assistant")
            args = {"invoice": f"INV-{answered + 1}"}
            r.tool_calls = [
                {
                    "id": f"call_{answered + 1}",
                    "type": "function",
                    "function": {"name": "pay_invoice", "arguments": json.dumps(args)},
                }
            ]
        else:
            r = ModelResponse(content="Paid.", role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        r.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return r

    def invoke(self, *a, **k):
        return self._next(k["messages"])

    async def ainvoke(self, *a, **k):
        return self._next(k["messages"])

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next(k["messages"])

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next(k["messages"])

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


@approval
@tool(requires_confirmation=True)
def pay_invoice(invoice: str) -> str:
    """Pay a vendor invoice.

    Args:
        invoice (str): Invoice number
    """
    PAID.append(invoice)
    return f"PAID {invoice}"


@pytest.fixture
def client(shared_db):
    PAID.clear()
    agent = Agent(id="invoice-agent", model=InvoiceScriptedModel(), tools=[pay_invoice], db=shared_db, telemetry=False)
    team = Team(
        id="invoice-team",
        model=InvoiceScriptedModel(),
        members=[Agent(id="helper", model=InvoiceScriptedModel(), telemetry=False)],
        tools=[pay_invoice],
        db=shared_db,
        telemetry=False,
    )
    app = AgentOS(agents=[agent], teams=[team], db=shared_db, telemetry=False).get_app()
    return TestClient(app)


COMPONENTS = [pytest.param(("agents", "invoice-agent"), id="agent"), pytest.param(("teams", "invoice-team"), id="team")]


def _start(client: TestClient, kind: str, component_id: str) -> dict:
    resp = client.post(f"/{kind}/{component_id}/runs", data={"message": "Pay INV-1 and INV-2.", "stream": "false"})
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["status"] == "PAUSED"
    return run


def _continue(client: TestClient, kind: str, component_id: str, run: dict):
    return client.post(
        f"/{kind}/{component_id}/runs/{run['run_id']}/continue",
        data={"tools": "", "session_id": run["session_id"], "stream": "false"},
    )


def _records(client: TestClient, run_id: str, status: str = "") -> List[dict]:
    params = {"run_id": run_id, "approval_type": "required"}
    if status:
        params["status"] = status
    resp = client.get("/approvals", params=params)
    assert resp.status_code == 200, resp.text
    return sorted(resp.json()["data"], key=lambda r: r["created_at"])


def _named_calls(record: dict) -> List[str]:
    return [(r.get("tool_execution") or {}).get("tool_call_id") for r in record.get("requirements") or []]


def _resolve(client: TestClient, approval_id: str, status: str) -> None:
    resp = client.post(f"/approvals/{approval_id}/resolve", json={"status": status, "resolved_by": "admin"})
    assert resp.status_code == 200, resp.text


def _pause_on_second_call(client: TestClient, kind: str, component_id: str) -> dict:
    """Start a run, approve INV-1, continue: the run pauses again on INV-2."""
    run = _start(client, kind, component_id)
    (first,) = _records(client, run["run_id"], "pending")
    assert _named_calls(first) == ["call_1"]
    _resolve(client, first["id"], "approved")

    resp = _continue(client, kind, component_id, run)
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["status"] == "PAUSED"
    assert PAID == ["INV-1"]
    return run


@pytest.mark.parametrize("component", COMPONENTS)
def test_second_call_surfaces_its_own_pending_approval(client, component):
    kind, component_id = component
    run = _pause_on_second_call(client, kind, component_id)

    pending = _records(client, run["run_id"], "pending")
    assert len(pending) == 1
    assert _named_calls(pending[0]) == ["call_2"]
    assert pending[0]["tool_args"] == {"invoice": "INV-2"}

    _resolve(client, pending[0]["id"], "approved")
    resp = _continue(client, kind, component_id, run)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "COMPLETED"
    assert PAID == ["INV-1", "INV-2"]

    records = _records(client, run["run_id"])
    assert [_named_calls(r) for r in records] == [["call_1"], ["call_2"]]
    assert [(r["status"], r["resolved_by"]) for r in records] == [("approved", "admin"), ("approved", "admin")]


@pytest.mark.parametrize("component", COMPONENTS)
def test_second_call_does_not_run_while_its_approval_is_pending(client, component):
    kind, component_id = component
    run = _pause_on_second_call(client, kind, component_id)

    resp = _continue(client, kind, component_id, run)
    if resp.status_code == 200:
        assert resp.json()["status"] == "PAUSED"
    else:
        assert 400 <= resp.status_code < 500, resp.text
    assert PAID == ["INV-1"]
    assert len(_records(client, run["run_id"], "pending")) == 1


@pytest.mark.parametrize("component", COMPONENTS)
def test_rejecting_second_call_keeps_it_from_running(client, component):
    kind, component_id = component
    run = _pause_on_second_call(client, kind, component_id)

    (pending,) = _records(client, run["run_id"], "pending")
    _resolve(client, pending["id"], "rejected")
    resp = _continue(client, kind, component_id, run)
    assert resp.status_code == 200, resp.text
    assert PAID == ["INV-1"]
    assert [r["status"] for r in _records(client, run["run_id"])] == ["approved", "rejected"]
