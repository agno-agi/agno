import importlib.util
import json
from pathlib import Path

import pytest

from agno.tools import FunctionCall


COOKBOOK_PATH = Path(__file__).parents[5] / "cookbook" / "91_tools" / "tool_hooks" / "deterministic_governance.py"


def load_cookbook_module():
    spec = importlib.util.spec_from_file_location("deterministic_governance", COOKBOOK_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_governance_denies_tool_before_side_effect():
    module = load_cookbook_module()
    tools = module.CustomerAccountTools()
    governance = module.DeterministicGovernance(denylist={"delete_customer"})
    delete_tool = tools.functions["delete_customer"]
    delete_tool.tool_hooks = [governance.sync_hook]

    result = FunctionCall(function=delete_tool, arguments={"customer_id": "cust-123"}).execute()

    assert result.status == "success"
    assert isinstance(result.result, str)
    decision = json.loads(result.result)
    assert decision == {
        "allowed": False,
        "action": "deny",
        "reason": "tool 'delete_customer' is denied by policy",
    }
    assert tools.deleted_customers == []


def test_governance_redacts_pii_from_tool_result():
    module = load_cookbook_module()
    tools = module.CustomerAccountTools()
    governance = module.DeterministicGovernance(allowlist={"lookup_customer"}, redact_pii=True)
    lookup_tool = tools.functions["lookup_customer"]
    lookup_tool.tool_hooks = [governance.sync_hook]

    result = FunctionCall(function=lookup_tool, arguments={"customer_id": "cust-123"}).execute()

    assert result.status == "success"
    assert isinstance(result.result, str)
    assert "[REDACTED_EMAIL]" in result.result
    assert "[REDACTED_PHONE]" in result.result
    assert "jane.customer@example.com" not in result.result
    assert "555-120-4567" not in result.result


@pytest.mark.asyncio
async def test_async_governance_enforces_budget_and_freeze():
    module = load_cookbook_module()
    tools = module.AsyncCustomerAccountTools()
    governance = module.DeterministicGovernance(allowlist={"lookup_customer"}, max_tool_calls=1)
    lookup_tool = tools.async_functions["lookup_customer"]
    lookup_tool.tool_hooks = [governance.async_hook]

    first = await FunctionCall(function=lookup_tool, arguments={"customer_id": "cust-123"}).aexecute()
    second = await FunctionCall(function=lookup_tool, arguments={"customer_id": "cust-456"}).aexecute()

    assert first.status == "success"
    assert isinstance(first.result, str)
    assert "cust-123" in first.result
    assert second.status == "success"
    assert isinstance(second.result, str)
    assert json.loads(second.result) == {
        "allowed": False,
        "action": "deny",
        "reason": "tool budget exceeded",
    }

    governance.freeze("incident-42")
    frozen = await FunctionCall(function=lookup_tool, arguments={"customer_id": "cust-789"}).aexecute()

    assert isinstance(frozen.result, str)
    assert json.loads(frozen.result) == {
        "allowed": False,
        "action": "deny",
        "reason": "governance kill switch active: incident-42",
    }
