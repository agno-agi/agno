"""The learning decision log, scoped to Company without a separate table."""

from dataclasses import asdict
from typing import Any, Optional

from agno.db.base import AsyncBaseDb, BaseDb
from agno.learn.config import DecisionLogConfig
from agno.learn.schemas import DecisionLog
from agno.learn.stores.decision_log import DecisionLogStore


class CompanyDecisionLogStore(DecisionLogStore):
    """Use the learning domain's schema, context and tools with a Company namespace.

    API writes propagate storage failures instead of reporting a saved decision
    after the general-purpose learning store's best-effort save has failed.
    """

    def __init__(self, db: Any, user_isolation: bool = False):
        super().__init__(config=DecisionLogConfig(db=db))
        self.user_isolation = user_isolation

    def recall(self, **kwargs):
        """Recall across Company authors; use search for explicit agent filtering."""
        from agno.tools.company import _permission

        _permission("decisions", "read", kwargs.get("run_context"))
        # Runtime agent identity must not hide human or other agents' decisions.
        # Explicit search retains its optional agent filter.
        kwargs.pop("agent_id", None)
        return super().recall(**kwargs)

    async def arecall(self, **kwargs):
        """Async recall across Company authors, including human decisions."""
        from agno.tools.company import _apermission

        await _apermission("decisions", "read", kwargs.get("run_context"))
        kwargs.pop("agent_id", None)
        return await super().arecall(**kwargs)

    def save(self, decision: DecisionLog) -> None:
        if not isinstance(self.db, BaseDb):
            raise TypeError("Use asave with an asynchronous database")
        self.db.upsert_learning(
            id=decision.id,
            learning_type=self.learning_type,
            namespace="company",
            entity_id=decision.id,
            content=asdict(decision),
            user_id=decision.user_id,
            agent_id=decision.agent_id,
            session_id=decision.session_id,
            team_id=decision.team_id,
        )
        if self.db.get_learning(learning_type=self.learning_type, namespace="company", entity_id=decision.id) is None:
            raise RuntimeError("Company decision was not persisted")
        self.decisions_updated = True

    async def asave(self, decision: DecisionLog) -> None:
        if isinstance(self.db, AsyncBaseDb):
            await self.db.upsert_learning(
                id=decision.id,
                learning_type=self.learning_type,
                namespace="company",
                entity_id=decision.id,
                content=asdict(decision),
                user_id=decision.user_id,
                agent_id=decision.agent_id,
                session_id=decision.session_id,
                team_id=decision.team_id,
            )
            if (
                await self.db.get_learning(learning_type=self.learning_type, namespace="company", entity_id=decision.id)
                is None
            ):
                raise RuntimeError("Company decision was not persisted")
            self.decisions_updated = True
        else:
            import asyncio

            await asyncio.to_thread(self.save, decision)

    def search(self, query=None, agent_id=None, session_id=None, decision_type=None, days=None, limit=10):
        if not isinstance(self.db, BaseDb):
            raise TypeError("Use asearch with an asynchronous database")
        rows = self.db.get_learnings(
            learning_type=self.learning_type, namespace="company", agent_id=agent_id, session_id=session_id
        )
        return self._filter_decisions(
            rows, query=query, decision_type=decision_type, days=days, limit=len(rows) if limit is None else limit
        )

    async def asearch(self, query=None, agent_id=None, session_id=None, decision_type=None, days=None, limit=10):
        if isinstance(self.db, AsyncBaseDb):
            rows = await self.db.get_learnings(
                learning_type=self.learning_type, namespace="company", agent_id=agent_id, session_id=session_id
            )
            return self._filter_decisions(
                rows, query=query, decision_type=decision_type, days=days, limit=len(rows) if limit is None else limit
            )
        import asyncio

        return await asyncio.to_thread(self.search, query, agent_id, session_id, decision_type, days, limit)

    def instructions(self) -> str:
        """Describe only the bounded Company decision tools exposed to the agent."""
        if not self._should_expose_tools:
            return ""
        return (
            "<decision_log_instructions>\n"
            "Use `log_company_decision` to record significant decisions with reasoning, context and observed outcome.\n"
            "Use `search_company_decisions` to find past company decisions, including human decisions.\n"
            "The log is append-only. To record a later outcome, append a new decision that references the original "
            "decision and describes the observed outcome; existing entries cannot be updated.\n"
            "</decision_log_instructions>"
        )

    def get_tools(self, agent_id: Optional[str] = None, **kwargs):
        from agno.tools.company import CompanyTools

        if not self._should_expose_tools:
            return []
        tools = CompanyTools(self.db, user_isolation=self.user_isolation, agent_id=agent_id)
        return [tools.log_company_decision, tools.search_company_decisions]

    async def aget_tools(self, agent_id: Optional[str] = None, **kwargs):
        from agno.tools.company import CompanyTools

        if not self._should_expose_tools:
            return []
        tools = CompanyTools(self.db, user_isolation=self.user_isolation, agent_id=agent_id)
        return [
            tools.get_async_functions()["log_company_decision"],
            tools.get_async_functions()["search_company_decisions"],
        ]


def _new_decision(
    decision: str,
    reasoning: Optional[str],
    context: Optional[str],
    outcome: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
    agent_id: Optional[str],
) -> DecisionLog:
    from datetime import datetime, timezone
    from uuid import uuid4

    if not decision.strip():
        raise ValueError("decision must be non-empty")
    return DecisionLog(
        id=str(uuid4()),
        decision=decision,
        reasoning=reasoning,
        context=context,
        outcome=outcome,
        user_id=user_id,
        session_id=session_id,
        agent_id=agent_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
