"""
MCP Recovery and Duplicate-Resistant Execution
================================================

Demonstrates a reliability sidecar around an external create operation:

- Plan the guard sequence from closed capability facts.
- Recover a failed checkpoint generation.
- Fence a competing worker before the external side effect.
- Resolve a lost response by reading a stable marker instead of creating again.
- Record caller-supplied verification evidence without claiming external proof.

The Agent Enhancer MCP endpoint is public and requires no account or API key.
The destination is deliberately synthetic and local, so this example is safe to run.

Run: `uv run --with "agno[mcp]" python
cookbook/91_tools/mcp/reliability_sidecar/recovery_and_duplicate_resistance.py`
"""

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from agno.tools.function import FunctionCall, ToolResult
from agno.tools.mcp import MCPTools

AGENT_ENHANCER_MCP_URL = "https://liberated.site/mcp?source=agno-cookbook-reliability"


# ---------------------------------------------------------------------------
# Create Synthetic Destination
# ---------------------------------------------------------------------------


@dataclass
class SyntheticDestination:
    """A destination that can create duplicates and supports marker lookup."""

    records: list[dict[str, str]] = field(default_factory=list)
    create_attempts: int = 0

    def create(self, marker: str) -> dict[str, str]:
        self.create_attempts += 1
        record = {"id": f"synthetic-{self.create_attempts}", "marker": marker}
        self.records.append(record)
        return record

    def find_by_marker(self, marker: str) -> list[dict[str, str]]:
        return [record for record in self.records if record["marker"] == marker]


# ---------------------------------------------------------------------------
# MCP Helpers
# ---------------------------------------------------------------------------


async def call_agno_tool(
    tools: MCPTools,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Execute a registered MCP tool through Agno's FunctionCall path."""
    function = tools.functions[name]
    execution = await FunctionCall(function=function, arguments=arguments).aexecute()
    if execution.status != "success":
        raise RuntimeError(f"{name} failed: {execution.error}")

    result = execution.result
    if not isinstance(result, ToolResult) or not result.content:
        raise RuntimeError(f"{name} returned no JSON ToolResult")

    payload = json.loads(result.content)
    if payload.get("ok") is not True:
        raise RuntimeError(f"{name} returned an error: {payload}")
    return payload


async def invoke_module(
    tools: MCPTools,
    slug: str,
    module_input: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Invoke one progressive-discovery module and unwrap its result."""
    arguments: dict[str, Any] = {"slug": slug, "input": module_input}
    if idempotency_key is not None:
        arguments["idempotency_key"] = idempotency_key
    envelope = await call_agno_tool(tools, "lab.invoke_tool", arguments)
    return envelope["result"]


# ---------------------------------------------------------------------------
# Reliability Inputs
# ---------------------------------------------------------------------------


def opaque_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scoped_idempotency_key(namespace: str, workflow_key: str, step: str) -> str:
    """Return a stable key that a transport retry can safely reuse."""
    digest = opaque_digest(f"{namespace}|{workflow_key}|{step}")
    return f"agno_{digest}"


def evidence_fingerprint(record: dict[str, str], local_key: bytes) -> str:
    """Fingerprint local readback evidence without sending the record."""
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return f"hmac-sha256:{hmac.new(local_key, canonical, hashlib.sha256).hexdigest()}"


def checkpoint_claim(
    namespace: str,
    workflow_key: str,
    holder: str,
) -> dict[str, Any]:
    return {
        "action": "claim",
        "namespace": namespace,
        "workflow_key": workflow_key,
        "holder": holder,
        "claim_ttl_seconds": 60,
        "state_ttl_seconds": 600,
        "retry_failed": True,
    }


def checkpoint_transition(
    *,
    namespace: str,
    workflow_key: str,
    holder: str,
    generation: int,
    from_stage: str,
    to_stage: str,
    observation: str,
    evidence_type: str | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    return {
        "action": "transition",
        "namespace": namespace,
        "workflow_key": workflow_key,
        "holder": holder,
        "expected_generation": generation,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "observation_key": opaque_digest(observation),
        "evidence_type": evidence_type,
        "evidence_fingerprint": evidence,
    }


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------


async def run_demo() -> None:
    destination = SyntheticDestination()
    namespace = f"agno-reliability:{uuid4()}"
    workflow_key = opaque_digest("synthetic-create:customer-042")
    marker = opaque_digest("customer-042")
    primary_holder = f"holder_{opaque_digest('primary')[:24]}"
    recovery_holder = f"holder_{opaque_digest('recovery')[:24]}"
    competing_holder = f"holder_{opaque_digest('competing')[:24]}"
    local_evidence_key = uuid4().bytes

    def request_key(step: str) -> str:
        return scoped_idempotency_key(namespace, workflow_key, step)

    async with MCPTools(
        transport="streamable-http",
        url=AGENT_ENHANCER_MCP_URL,
        timeout_seconds=30,
        include_tools=["lab.invoke_tool"],
    ) as enhancer:
        # 1. Ask the sidecar for the strongest honest guarantee.
        plan = await invoke_module(
            enhancer,
            "workflow-guard-planner",
            {
                "contract_version": "1",
                "operation_class": "create",
                "item_operation_class": None,
                "duplicate_harm": "material",
                "parallel_workers": 2,
                "scheduled": False,
                "retry_possible": True,
                "provider_idempotency": "none",
                "destination_search": "strong",
                "stable_marker": True,
                "conditional_write": False,
                "read_after_write": True,
                "delivery_status": False,
                "compensation": "manual",
                "shared_rate_limit": False,
                "maximum_concurrency": None,
                "freshness_required": False,
            },
        )
        assert plan["decision"] == "sidecar"
        assert plan["guarantee"] == "duplicate-resistant"
        assert "cross_plugin_exactly_once" in plan["unsupported_claims"]

        # 2. Generation 1 fails before any external side effect.
        first_claim = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_claim(namespace, workflow_key, primary_holder),
            request_key("claim-generation-1"),
        )
        assert first_claim["acquired"] is True

        failed = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_transition(
                namespace=namespace,
                workflow_key=workflow_key,
                holder=primary_holder,
                generation=first_claim["generation"],
                from_stage="claimed",
                to_stage="failed",
                observation="provider rejected before write",
            ),
            request_key("fail-generation-1"),
        )
        assert failed["stage"] == "failed"
        assert destination.create_attempts == 0

        # 3. A recovery worker opens generation 2.
        recovery_claim = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_claim(namespace, workflow_key, recovery_holder),
            request_key("claim-generation-2"),
        )
        assert recovery_claim["acquired"] is True
        assert recovery_claim["recovered"] is True
        assert recovery_claim["generation"] == 2

        # A competing worker is fenced out while generation 2 is active.
        competing_claim = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_claim(namespace, workflow_key, competing_holder),
            request_key("competing-claim-generation-2"),
        )
        assert competing_claim["acquired"] is False
        assert competing_claim["held_by_caller"] is False

        # 4. The destination creates the record, but its response is "lost".
        destination.create(marker)
        uncertain = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_transition(
                namespace=namespace,
                workflow_key=workflow_key,
                holder=recovery_holder,
                generation=recovery_claim["generation"],
                from_stage="claimed",
                to_stage="external_result_uncertain",
                observation="connection closed after destination write",
            ),
            request_key("uncertain-generation-2"),
        )
        assert uncertain["stage"] == "external_result_uncertain"

        # 5. The same logical worker resumes with its stable opaque holder ID.
        resumed = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_claim(namespace, workflow_key, recovery_holder),
            request_key("resume-generation-2"),
        )
        assert resumed["acquired"] is True
        assert resumed["reused"] is True

        matches = destination.find_by_marker(marker)
        assert len(matches) == 1
        # Do not call destination.create again: marker readback resolved the timeout.

        verified = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            checkpoint_transition(
                namespace=namespace,
                workflow_key=workflow_key,
                holder=recovery_holder,
                generation=resumed["generation"],
                from_stage="external_result_uncertain",
                to_stage="caller_verified",
                observation="stable marker readback found one record",
                evidence_type="stable_marker_readback",
                evidence=evidence_fingerprint(matches[0], local_evidence_key),
            ),
            request_key("verify-generation-2"),
        )
        assert verified["stage"] == "caller_verified"
        assert verified["external_proof"] is False

        final_status = await invoke_module(
            enhancer,
            "workflow-checkpoint",
            {
                "action": "status",
                "namespace": namespace,
                "workflow_key": workflow_key,
            },
            request_key("final-status"),
        )
        assert final_status["stage"] == "caller_verified"

    print(
        json.dumps(
            {
                "planned_guarantee": plan["guarantee"],
                "recovered_generation": recovery_claim["generation"],
                "competing_worker_admitted": competing_claim["acquired"],
                "external_create_attempts": destination.create_attempts,
                "matching_records": len(matches),
                "final_stage": final_status["stage"],
                "external_proof": final_status["external_proof"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run_demo())
