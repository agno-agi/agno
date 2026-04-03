"""
MnemoPay toolkit — persistent memory + micropayments for Agno agents.

MnemoPay gives every agent a wallet and long-term memory that survive across
sessions. Memory operations (remember, recall, forget, reinforce, consolidate)
use time-weighted scoring so that stale facts decay while reinforced facts stay
fresh. Payment operations (charge, settle, refund) use escrow-based
micropayments tied to a reputation system.

Install:
    pip install mnemopay-agno

Usage:
    from agno.agent import Agent
    from agno.tools.mnemopay import MnemoPayTools

    agent = Agent(tools=[MnemoPayTools()])
"""

import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from mnemopay_agno import MnemoPayTools as _ExternalMnemoPayTools  # noqa: F401
except ImportError:
    raise ImportError("`mnemopay-agno` not installed. Please install using `pip install mnemopay-agno`")


class MnemoPayTools(Toolkit):
    """MnemoPay toolkit: persistent memory + micropayments for any Agno agent.

    Provides two categories of tools:

    **Memory** — Store, search, boost, and prune agent memories that persist
    across sessions using time-weighted importance scoring.

    **Payments** — Escrow-based micropayments with a built-in reputation
    system. Agents charge for work delivered, settle to release funds, and
    build on-chain reputation over time.

    Args:
        server_url (str, optional): MnemoPay MCP server URL. Falls back to
            ``MNEMOPAY_SERVER_URL`` environment variable. When omitted,
            the client spawns a local stdio server via ``npx @mnemopay/sdk``.
        agent_id (str): Unique identifier for this agent instance.
        enable_remember (bool): Register the ``remember`` tool.
        enable_recall (bool): Register the ``recall`` tool.
        enable_forget (bool): Register the ``forget`` tool.
        enable_reinforce (bool): Register the ``reinforce`` tool.
        enable_consolidate (bool): Register the ``consolidate`` tool.
        enable_charge (bool): Register the ``charge`` tool.
        enable_settle (bool): Register the ``settle`` tool.
        enable_refund (bool): Register the ``refund`` tool.
        enable_balance (bool): Register the ``balance`` tool.
        enable_profile (bool): Register the ``profile`` tool.
        enable_logs (bool): Register the ``logs`` tool.
        enable_history (bool): Register the ``history`` tool.
        all (bool): Enable all tools regardless of individual flags.
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
        agent_id: str = "agno-agent",
        enable_remember: bool = True,
        enable_recall: bool = True,
        enable_forget: bool = True,
        enable_reinforce: bool = True,
        enable_consolidate: bool = True,
        enable_charge: bool = True,
        enable_settle: bool = True,
        enable_refund: bool = True,
        enable_balance: bool = True,
        enable_profile: bool = True,
        enable_logs: bool = True,
        enable_history: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.server_url = server_url or getenv("MNEMOPAY_SERVER_URL")
        self.agent_id = agent_id
        self._client: Optional[_ExternalMnemoPayTools] = None

        tools: List[Callable] = []

        # Memory tools
        if all or enable_remember:
            tools.append(self.remember)
        if all or enable_recall:
            tools.append(self.recall)
        if all or enable_forget:
            tools.append(self.forget)
        if all or enable_reinforce:
            tools.append(self.reinforce)
        if all or enable_consolidate:
            tools.append(self.consolidate)

        # Payment tools
        if all or enable_charge:
            tools.append(self.charge)
        if all or enable_settle:
            tools.append(self.settle)
        if all or enable_refund:
            tools.append(self.refund)
        if all or enable_balance:
            tools.append(self.balance)

        # Observability tools
        if all or enable_profile:
            tools.append(self.profile)
        if all or enable_logs:
            tools.append(self.logs)
        if all or enable_history:
            tools.append(self.history)

        super().__init__(name="mnemopay", tools=tools, **kwargs)

    @property
    def client(self) -> _ExternalMnemoPayTools:
        """Lazy-initialised MnemoPay client."""
        if self._client is None:
            self._client = _ExternalMnemoPayTools(
                server_url=self.server_url,
                agent_id=self.agent_id,
            )
        return self._client

    # ── Memory tools ────────────────────────────────────────────────────────

    def remember(self, content: str, importance: Optional[float] = None) -> str:
        """Store a memory that persists across sessions.

        Use for facts, user preferences, decisions, and anything the agent
        should recall later. Memories are scored by time-weighted importance.

        Args:
            content (str): The text to remember.
            importance (float, optional): Initial importance score (0.0-1.0).

        Returns:
            str: JSON string confirming the stored memory.
        """
        log_debug(f"MnemoPay: storing memory (importance={importance})")
        result = self.client.remember(content=content, importance=importance)
        return self._wrap(result)

    def recall(self, query: Optional[str] = None, limit: int = 5) -> str:
        """Recall relevant memories via semantic search.

        Args:
            query (str, optional): Natural-language search query. When omitted,
                returns the most recent memories.
            limit (int): Maximum number of memories to return. Default is 5.

        Returns:
            str: JSON string containing matching memories.
        """
        log_debug(f"MnemoPay: recalling memories (query={query!r}, limit={limit})")
        result = self.client.recall(query=query, limit=limit)
        return self._wrap(result)

    def forget(self, id: str) -> str:
        """Permanently delete a memory by ID.

        Args:
            id (str): The memory ID to delete.

        Returns:
            str: JSON string confirming deletion.
        """
        log_debug(f"MnemoPay: forgetting memory {id}")
        result = self.client.forget(id=id)
        return self._wrap(result)

    def reinforce(self, id: str, boost: float = 0.1) -> str:
        """Boost a memory's importance after it proved valuable.

        Call this when a previously recalled memory turns out to be useful,
        keeping it alive longer during consolidation.

        Args:
            id (str): The memory ID to reinforce.
            boost (float): Amount to increase importance by. Default is 0.1.

        Returns:
            str: JSON string with updated memory score.
        """
        log_debug(f"MnemoPay: reinforcing memory {id} by {boost}")
        result = self.client.reinforce(id=id, boost=boost)
        return self._wrap(result)

    def consolidate(self) -> str:
        """Prune stale memories whose scores have decayed below threshold.

        Run periodically to keep the memory store lean. Memories that have
        not been reinforced will naturally decay and get removed.

        Returns:
            str: JSON string with consolidation summary.
        """
        log_debug("MnemoPay: consolidating memories")
        result = self.client.consolidate()
        return self._wrap(result)

    # ── Payment tools ───────────────────────────────────────────────────────

    def charge(self, amount: float, reason: str) -> str:
        """Create an escrow charge for work delivered.

        Only charge AFTER delivering value. The charge enters escrow until
        the user or system calls ``settle``.

        Args:
            amount (float): Amount in USD to charge.
            reason (str): Human-readable description of the work performed.

        Returns:
            str: JSON string with transaction ID and escrow details.
        """
        log_debug(f"MnemoPay: charging ${amount} — {reason}")
        result = self.client.charge(amount=amount, reason=reason)
        return self._wrap(result)

    def settle(self, tx_id: str) -> str:
        """Finalize a pending escrow transaction.

        Releases funds from escrow, boosts the agent's reputation score,
        and reinforces recent memories that contributed to the settlement.

        Args:
            tx_id (str): Transaction ID to settle.

        Returns:
            str: JSON string confirming settlement.
        """
        log_debug(f"MnemoPay: settling transaction {tx_id}")
        result = self.client.settle(tx_id=tx_id)
        return self._wrap(result)

    def refund(self, tx_id: str) -> str:
        """Refund a transaction and dock reputation.

        Returns funds from escrow and applies a -0.05 reputation penalty.

        Args:
            tx_id (str): Transaction ID to refund.

        Returns:
            str: JSON string confirming refund.
        """
        log_debug(f"MnemoPay: refunding transaction {tx_id}")
        result = self.client.refund(tx_id=tx_id)
        return self._wrap(result)

    def balance(self) -> str:
        """Check wallet balance and reputation score.

        Returns:
            str: JSON string with current balance and reputation.
        """
        log_debug("MnemoPay: checking balance")
        result = self.client.balance()
        return self._wrap(result)

    # ── Observability tools ─────────────────────────────────────────────────

    def profile(self) -> str:
        """Full agent profile: reputation, wallet, memory count, transaction count.

        Returns:
            str: JSON string with comprehensive agent statistics.
        """
        log_debug("MnemoPay: fetching profile")
        result = self.client.profile()
        return self._wrap(result)

    def logs(self, limit: int = 20) -> str:
        """Immutable audit trail of all memory and payment actions.

        Args:
            limit (int): Maximum number of log entries. Default is 20.

        Returns:
            str: JSON string with audit log entries.
        """
        log_debug(f"MnemoPay: fetching logs (limit={limit})")
        result = self.client.logs(limit=limit)
        return self._wrap(result)

    def history(self, limit: int = 10) -> str:
        """Transaction history, most recent first.

        Args:
            limit (int): Maximum number of transactions. Default is 10.

        Returns:
            str: JSON string with transaction history.
        """
        log_debug(f"MnemoPay: fetching history (limit={limit})")
        result = self.client.history(limit=limit)
        return self._wrap(result)

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _wrap(result: str) -> str:
        """Ensure the result is valid JSON; wrap plain text if needed."""
        try:
            json.loads(result)
            return result
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"result": str(result)})
