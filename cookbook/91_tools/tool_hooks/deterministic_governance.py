"""Deterministic tool governance with Agno tool hooks.

This example keeps governance provider-neutral. The hook receives the tool name,
arguments, and continuation function before the real tool body runs, so it can
make an allow/deny decision without asking the model.
"""

import json
import re
from inspect import iscoroutinefunction
from typing import Any, Callable, Dict, Optional, Set

from agno.tools import Toolkit
from agno.utils.log import logger


# ---------------------------------------------------------------------------
# Governance hook
# ---------------------------------------------------------------------------


class DeterministicGovernance:
    """Small provider-neutral governance hook for tool execution.

    This is intentionally plain Python. Replace the policy methods with a call
    to TealTiger, HOL Guard, or an internal policy engine while keeping the Agno
    integration point the same: a `tool_hooks` callable that either returns a
    deny result or calls the continuation.
    """

    EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    PHONE_RE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")

    def __init__(
        self,
        *,
        allowlist: Optional[Set[str]] = None,
        denylist: Optional[Set[str]] = None,
        redact_pii: bool = True,
        max_tool_calls: Optional[int] = None,
    ) -> None:
        self.allowlist = allowlist
        self.denylist = denylist or set()
        self.redact_pii = redact_pii
        self.max_tool_calls = max_tool_calls
        self.tool_calls = 0
        self.freeze_reason: Optional[str] = None

    def freeze(self, reason: str) -> None:
        """Activate the kill switch for later tool calls."""

        self.freeze_reason = reason

    def _deny(self, reason: str) -> str:
        return json.dumps({"allowed": False, "action": "deny", "reason": reason})

    def _authorize(self, function_name: str) -> Optional[str]:
        if self.freeze_reason is not None:
            return f"governance kill switch active: {self.freeze_reason}"
        if function_name in self.denylist:
            return f"tool '{function_name}' is denied by policy"
        if self.allowlist is not None and function_name not in self.allowlist:
            return f"tool '{function_name}' is not on the allowlist"
        if self.max_tool_calls is not None and self.tool_calls >= self.max_tool_calls:
            return "tool budget exceeded"
        return None

    def _redact(self, value: Any) -> Any:
        if not self.redact_pii or not isinstance(value, str):
            return value
        value = self.EMAIL_RE.sub("[REDACTED_EMAIL]", value)
        return self.PHONE_RE.sub("[REDACTED_PHONE]", value)

    def sync_hook(
        self,
        function_name: str,
        function_call: Callable[..., Any],
        arguments: Dict[str, Any],
    ) -> Any:
        """Authorize a sync tool call before executing the real tool body."""

        denial_reason = self._authorize(function_name)
        if denial_reason is not None:
            return self._deny(denial_reason)

        self.tool_calls += 1
        result = function_call(**arguments)
        return self._redact(result)

    async def async_hook(
        self,
        function_name: str,
        function_call: Callable[..., Any],
        arguments: Dict[str, Any],
    ) -> Any:
        """Authorize an async tool call before executing the real tool body."""

        denial_reason = self._authorize(function_name)
        if denial_reason is not None:
            return self._deny(denial_reason)

        self.tool_calls += 1
        if iscoroutinefunction(function_call):
            result = await function_call(**arguments)
        else:
            result = function_call(**arguments)
        return self._redact(result)


# ---------------------------------------------------------------------------
# Create demo tools
# ---------------------------------------------------------------------------


class CustomerAccountTools(Toolkit):
    def __init__(self) -> None:
        super().__init__(name="customer_account_tools")
        self.deleted_customers: list[str] = []
        self.register(self.lookup_customer)
        self.register(self.delete_customer)

    def lookup_customer(self, customer_id: str) -> str:
        """Look up a customer record.

        Args:
            customer_id: Customer identifier.
        """

        return json.dumps(
            {
                "customer_id": customer_id,
                "name": "Jane Customer",
                "email": "jane.customer@example.com",
                "phone": "555-120-4567",
            }
        )

    def delete_customer(self, customer_id: str) -> str:
        """Delete a customer record.

        Args:
            customer_id: Customer identifier.
        """

        self.deleted_customers.append(customer_id)
        return json.dumps({"deleted": customer_id})


class AsyncCustomerAccountTools(Toolkit):
    def __init__(self) -> None:
        super().__init__(name="async_customer_account_tools")
        self.register(self.lookup_customer)

    async def lookup_customer(self, customer_id: str) -> str:
        """Look up a customer record asynchronously.

        Args:
            customer_id: Customer identifier.
        """

        return json.dumps(
            {"customer_id": customer_id, "email": "jane.customer@example.com"}
        )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import asyncio

    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses

    governance = DeterministicGovernance(
        allowlist={"lookup_customer"},
        denylist={"delete_customer"},
        max_tool_calls=10,
    )
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        tools=[CustomerAccountTools()],
        tool_hooks=[governance.sync_hook],
        instructions="Use tools only after the deterministic governance hook allows them.",
    )

    logger.info("The lookup call is allowed and PII is redacted from the tool result.")
    agent.print_response("Look up customer cust-123")

    logger.info(
        "The delete call is denied before CustomerAccountTools.delete_customer runs."
    )
    agent.print_response("Delete customer cust-123")

    async_governance = DeterministicGovernance(
        allowlist={"lookup_customer"}, max_tool_calls=1
    )
    async_agent = Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        tools=[AsyncCustomerAccountTools()],
        tool_hooks=[async_governance.async_hook],
    )
    asyncio.run(async_agent.aprint_response("Look up customer cust-456"))
