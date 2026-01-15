"""
Decision Log Store
==================
Storage backend for Decision Log learning type.

Records decisions made by agents with reasoning, context, and outcomes.
Useful for auditing, debugging, and learning from past decisions.

Key Features:
- Log decisions with reasoning and context
- Record outcomes for feedback loops
- Search past decisions by type, time range, or content
- Agent tools for explicit decision logging

Scope:
- Decisions are stored per agent/session
- Can be queried by agent_id, session_id, or time range

Supported Modes:
- ALWAYS: Automatic extraction of decisions from tool calls
- AGENTIC: Agent explicitly logs decisions via tools
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from os import getenv
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union

from agno.learn.config import DecisionLogConfig, LearningMode
from agno.learn.schemas import DecisionLog
from agno.learn.stores.protocol import LearningStore
from agno.learn.utils import from_dict_safe, to_dict_safe
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

try:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.message import Message
except ImportError:
    pass


@dataclass
class DecisionLogStore(LearningStore):
    """Storage backend for Decision Log learning type.

    Records and retrieves decisions made by agents. Decisions include
    the choice made, reasoning, context, and optionally the outcome.

    Args:
        config: DecisionLogConfig with all settings including db and model.
        debug_mode: Enable debug logging.
    """

    config: DecisionLogConfig = field(default_factory=DecisionLogConfig)
    debug_mode: bool = False

    # State tracking (internal)
    decisions_updated: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or DecisionLog

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "decision_log"

    @property
    def schema(self) -> Any:
        """Schema class used for decisions."""
        return self._schema

    def recall(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        limit: int = 10,
        days: Optional[int] = None,
        **kwargs,
    ) -> Optional[List[DecisionLog]]:
        """Retrieve recent decisions.

        Args:
            agent_id: Filter by agent (optional).
            session_id: Filter by session (optional).
            decision_type: Filter by decision type (optional).
            limit: Maximum number of decisions to return.
            days: Only return decisions from last N days.
            **kwargs: Additional context (ignored).

        Returns:
            List of decisions, or None if none found.
        """
        return self.search(
            agent_id=agent_id,
            session_id=session_id,
            decision_type=decision_type,
            limit=limit,
            days=days,
        )

    async def arecall(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        limit: int = 10,
        days: Optional[int] = None,
        **kwargs,
    ) -> Optional[List[DecisionLog]]:
        """Async version of recall."""
        return await self.asearch(
            agent_id=agent_id,
            session_id=session_id,
            decision_type=decision_type,
            limit=limit,
            days=days,
        )

    def process(
        self,
        messages: List[Any],
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract decisions from messages (tool calls, etc).

        In ALWAYS mode, this extracts decisions from tool calls and
        significant response choices. In AGENTIC mode, this is a no-op
        as decisions are logged explicitly via tools.

        Args:
            messages: Conversation messages to analyze.
            agent_id: Agent context.
            session_id: Session context.
            user_id: User context.
            team_id: Team context.
            **kwargs: Additional context (ignored).
        """
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not messages:
            return

        # Extract decisions from tool calls in messages
        self._extract_decisions_from_messages(
            messages=messages,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
        )

    async def aprocess(
        self,
        messages: List[Any],
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not messages:
            return

        await self._aextract_decisions_from_messages(
            messages=messages,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
        )

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Formats recent decisions for injection into the agent's system prompt.

        Args:
            data: List of decisions from recall().

        Returns:
            Context string to inject into the agent's system prompt.
        """
        if not data:
            if self._should_expose_tools:
                return dedent("""\
                    <decision_log>
                    No recent decisions logged.

                    Use `log_decision` to record significant decisions with reasoning.
                    Use `search_decisions` to find past decisions.
                    </decision_log>""")
            return ""

        decisions = data if isinstance(data, list) else [data]

        context = "<decision_log>\n"
        context += "Recent decisions:\n\n"

        for decision in decisions[:5]:  # Limit to 5 most recent
            if isinstance(decision, DecisionLog):
                context += f"- **{decision.decision}**\n"
                if decision.reasoning:
                    context += f"  Reasoning: {decision.reasoning}\n"
                if decision.outcome:
                    context += f"  Outcome: {decision.outcome}\n"
                context += "\n"
            elif isinstance(decision, dict):
                context += f"- **{decision.get('decision', 'Unknown')}**\n"
                if decision.get("reasoning"):
                    context += f"  Reasoning: {decision['reasoning']}\n"
                if decision.get("outcome"):
                    context += f"  Outcome: {decision['outcome']}\n"
                context += "\n"

        if self._should_expose_tools:
            context += dedent("""
                Use `log_decision` to record new decisions.
                Use `search_decisions` to find past decisions.
                Use `record_outcome` to update a decision with its outcome.
            """)

        context += "</decision_log>"

        return context

    def get_tools(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools to expose to agent.

        Args:
            agent_id: Agent context.
            session_id: Session context.
            user_id: User context.
            team_id: Team context.
            **kwargs: Additional context (ignored).

        Returns:
            List containing decision logging and search tools if enabled.
        """
        if not self._should_expose_tools:
            return []
        return self.get_agent_tools(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
        )

    async def aget_tools(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        if not self._should_expose_tools:
            return []
        return await self.aget_agent_tools(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
        )

    @property
    def was_updated(self) -> bool:
        """Check if decisions were updated in last operation."""
        return self.decisions_updated

    @property
    def _should_expose_tools(self) -> bool:
        """Check if tools should be exposed to the agent."""
        return self.config.mode == LearningMode.AGENTIC or self.config.enable_agent_tools

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def db(self) -> Optional[Union["BaseDb", "AsyncBaseDb"]]:
        """Database backend."""
        return self.config.db

    @property
    def model(self):
        """Model for extraction."""
        return self.config.model

    # =========================================================================
    # Debug/Logging
    # =========================================================================

    def set_log_level(self):
        """Set log level based on debug_mode or environment variable."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    # =========================================================================
    # Agent Tools
    # =========================================================================

    def get_agent_tools(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get the tools to expose to the agent."""
        tools = []

        if self.config.agent_can_save:
            log_decision = self._build_log_decision_tool(
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                team_id=team_id,
            )
            if log_decision:
                tools.append(log_decision)

            record_outcome = self._build_record_outcome_tool(
                agent_id=agent_id,
                team_id=team_id,
            )
            if record_outcome:
                tools.append(record_outcome)

        if self.config.agent_can_search:
            search_decisions = self._build_search_decisions_tool(
                agent_id=agent_id,
                session_id=session_id,
            )
            if search_decisions:
                tools.append(search_decisions)

        return tools

    async def aget_agent_tools(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Async version of get_agent_tools."""
        tools = []

        if self.config.agent_can_save:
            log_decision = await self._abuild_log_decision_tool(
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                team_id=team_id,
            )
            if log_decision:
                tools.append(log_decision)

            record_outcome = await self._abuild_record_outcome_tool(
                agent_id=agent_id,
                team_id=team_id,
            )
            if record_outcome:
                tools.append(record_outcome)

        if self.config.agent_can_search:
            search_decisions = await self._abuild_search_decisions_tool(
                agent_id=agent_id,
                session_id=session_id,
            )
            if search_decisions:
                tools.append(search_decisions)

        return tools

    def _build_log_decision_tool(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Build the log_decision tool."""
        store = self

        def log_decision(
            decision: str,
            reasoning: Optional[str] = None,
            decision_type: Optional[str] = None,
            context: Optional[str] = None,
            alternatives: Optional[str] = None,
            confidence: Optional[float] = None,
        ) -> str:
            """Log a significant decision with reasoning.

            Use this to record important choices you make, especially:
            - Tool selection decisions
            - Response style choices
            - When you decide to ask for clarification
            - When you choose between different approaches

            Args:
                decision: What you decided to do.
                reasoning: Why you made this decision.
                decision_type: Category (tool_selection, response_style, clarification, etc).
                context: The situation that required this decision.
                alternatives: Other options you considered (comma-separated).
                confidence: How confident you are (0.0 to 1.0).

            Returns:
                Confirmation with decision ID.
            """
            try:
                decision_id = f"dec_{uuid.uuid4().hex[:8]}"
                alt_list = [a.strip() for a in alternatives.split(",")] if alternatives else None

                decision_obj = DecisionLog(
                    id=decision_id,
                    decision=decision,
                    reasoning=reasoning,
                    decision_type=decision_type,
                    context=context,
                    alternatives=alt_list,
                    confidence=confidence,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    created_at=datetime.utcnow().isoformat(),
                )

                store.save(decision=decision_obj)
                log_debug(f"DecisionLogStore: Logged decision {decision_id}")
                return f"Decision logged: {decision_id}"

            except Exception as e:
                log_warning(f"Error logging decision: {e}")
                return f"Error: {e}"

        return log_decision

    async def _abuild_log_decision_tool(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Async version of _build_log_decision_tool."""
        store = self

        async def log_decision(
            decision: str,
            reasoning: Optional[str] = None,
            decision_type: Optional[str] = None,
            context: Optional[str] = None,
            alternatives: Optional[str] = None,
            confidence: Optional[float] = None,
        ) -> str:
            """Log a significant decision with reasoning."""
            try:
                decision_id = f"dec_{uuid.uuid4().hex[:8]}"
                alt_list = [a.strip() for a in alternatives.split(",")] if alternatives else None

                decision_obj = DecisionLog(
                    id=decision_id,
                    decision=decision,
                    reasoning=reasoning,
                    decision_type=decision_type,
                    context=context,
                    alternatives=alt_list,
                    confidence=confidence,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    created_at=datetime.utcnow().isoformat(),
                )

                await store.asave(decision=decision_obj)
                log_debug(f"DecisionLogStore: Logged decision {decision_id}")
                return f"Decision logged: {decision_id}"

            except Exception as e:
                log_warning(f"Error logging decision: {e}")
                return f"Error: {e}"

        return log_decision

    def _build_record_outcome_tool(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Build the record_outcome tool."""
        store = self

        def record_outcome(
            decision_id: str,
            outcome: str,
            outcome_quality: Optional[str] = None,
        ) -> str:
            """Record the outcome of a previous decision.

            Use this to update a decision with what actually happened.
            This helps build feedback loops for learning.

            Args:
                decision_id: The ID of the decision to update.
                outcome: What happened as a result of the decision.
                outcome_quality: Was it good, bad, or neutral?

            Returns:
                Confirmation message.
            """
            try:
                success = store.update_outcome(
                    decision_id=decision_id,
                    outcome=outcome,
                    outcome_quality=outcome_quality,
                )
                if success:
                    return f"Outcome recorded for decision {decision_id}"
                else:
                    return f"Decision {decision_id} not found"

            except Exception as e:
                log_warning(f"Error recording outcome: {e}")
                return f"Error: {e}"

        return record_outcome

    async def _abuild_record_outcome_tool(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Async version of _build_record_outcome_tool."""
        store = self

        async def record_outcome(
            decision_id: str,
            outcome: str,
            outcome_quality: Optional[str] = None,
        ) -> str:
            """Record the outcome of a previous decision."""
            try:
                success = await store.aupdate_outcome(
                    decision_id=decision_id,
                    outcome=outcome,
                    outcome_quality=outcome_quality,
                )
                if success:
                    return f"Outcome recorded for decision {decision_id}"
                else:
                    return f"Decision {decision_id} not found"

            except Exception as e:
                log_warning(f"Error recording outcome: {e}")
                return f"Error: {e}"

        return record_outcome

    def _build_search_decisions_tool(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Build the search_decisions tool."""
        store = self

        def search_decisions(
            query: Optional[str] = None,
            decision_type: Optional[str] = None,
            days: Optional[int] = None,
            limit: int = 5,
        ) -> str:
            """Search past decisions.

            Use this to find relevant past decisions for context.

            Args:
                query: Text to search for in decisions.
                decision_type: Filter by type (tool_selection, response_style, etc).
                days: Only search last N days.
                limit: Maximum results to return.

            Returns:
                Formatted list of matching decisions.
            """
            try:
                results = store.search(
                    query=query,
                    decision_type=decision_type,
                    days=days,
                    limit=limit,
                    agent_id=agent_id,
                )

                if not results:
                    return "No matching decisions found."

                output = []
                for d in results:
                    line = f"[{d.id}] {d.decision}"
                    if d.reasoning:
                        line += f" - {d.reasoning[:50]}..."
                    if d.outcome:
                        line += f" -> {d.outcome[:30]}..."
                    output.append(line)

                return "\n".join(output)

            except Exception as e:
                log_warning(f"Error searching decisions: {e}")
                return f"Error: {e}"

        return search_decisions

    async def _abuild_search_decisions_tool(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Callable]:
        """Async version of _build_search_decisions_tool."""
        store = self

        async def search_decisions(
            query: Optional[str] = None,
            decision_type: Optional[str] = None,
            days: Optional[int] = None,
            limit: int = 5,
        ) -> str:
            """Search past decisions."""
            try:
                results = await store.asearch(
                    query=query,
                    decision_type=decision_type,
                    days=days,
                    limit=limit,
                    agent_id=agent_id,
                )

                if not results:
                    return "No matching decisions found."

                output = []
                for d in results:
                    line = f"[{d.id}] {d.decision}"
                    if d.reasoning:
                        line += f" - {d.reasoning[:50]}..."
                    if d.outcome:
                        line += f" -> {d.outcome[:30]}..."
                    output.append(line)

                return "\n".join(output)

            except Exception as e:
                log_warning(f"Error searching decisions: {e}")
                return f"Error: {e}"

        return search_decisions

    # =========================================================================
    # Read Operations
    # =========================================================================

    def search(
        self,
        query: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 10,
    ) -> List[DecisionLog]:
        """Search decisions with filters.

        Args:
            query: Text to search for.
            agent_id: Filter by agent.
            session_id: Filter by session.
            decision_type: Filter by type.
            days: Only last N days.
            limit: Maximum results.

        Returns:
            List of matching decisions.
        """
        if not self.db:
            return []

        # Ensure sync db for sync method
        if not isinstance(self.db, BaseDb):
            return []

        try:
            # Get all matching records
            results = self.db.get_learnings(
                learning_type=self.learning_type,
                agent_id=agent_id,
                limit=limit * 3,  # Over-fetch for filtering
            )

            if not results:
                return []

            decisions = []
            cutoff_date = None
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)

            for record in results:
                content = record.get("content") if isinstance(record, dict) else None
                if not content:
                    continue

                decision = from_dict_safe(DecisionLog, content)
                if not decision:
                    continue

                # Apply filters
                if decision_type and decision.decision_type != decision_type:
                    continue

                if cutoff_date and decision.created_at:
                    try:
                        created = datetime.fromisoformat(decision.created_at.replace("Z", "+00:00"))
                        if created < cutoff_date:
                            continue
                    except (ValueError, AttributeError):
                        pass

                if query:
                    query_lower = query.lower()
                    text = decision.to_text().lower()
                    if query_lower not in text:
                        continue

                decisions.append(decision)

                if len(decisions) >= limit:
                    break

            return decisions

        except Exception as e:
            log_debug(f"DecisionLogStore.search failed: {e}")
            return []

    async def asearch(
        self,
        query: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        days: Optional[int] = None,
        limit: int = 10,
    ) -> List[DecisionLog]:
        """Async version of search."""
        if not self.db:
            return []

        try:
            if isinstance(self.db, AsyncBaseDb):
                results = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    agent_id=agent_id,
                    limit=limit * 3,
                )
            else:
                results = self.db.get_learnings(
                    learning_type=self.learning_type,
                    agent_id=agent_id,
                    limit=limit * 3,
                )

            if not results:
                return []

            decisions = []
            cutoff_date = None
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)

            for record in results:
                content = record.get("content") if isinstance(record, dict) else None
                if not content:
                    continue

                decision = from_dict_safe(DecisionLog, content)
                if not decision:
                    continue

                if decision_type and decision.decision_type != decision_type:
                    continue

                if cutoff_date and decision.created_at:
                    try:
                        created = datetime.fromisoformat(decision.created_at.replace("Z", "+00:00"))
                        if created < cutoff_date:
                            continue
                    except (ValueError, AttributeError):
                        pass

                if query:
                    query_lower = query.lower()
                    text = decision.to_text().lower()
                    if query_lower not in text:
                        continue

                decisions.append(decision)

                if len(decisions) >= limit:
                    break

            return decisions

        except Exception as e:
            log_debug(f"DecisionLogStore.asearch failed: {e}")
            return []

    def get(self, decision_id: str) -> Optional[DecisionLog]:
        """Get a specific decision by ID."""
        if not self.db:
            return None

        # Ensure sync db for sync method
        if not isinstance(self.db, BaseDb):
            return None

        try:
            # Get learnings and filter by decision_id in content
            results = self.db.get_learnings(
                learning_type=self.learning_type,
                limit=100,
            )

            if not results:
                return None

            for record in results:
                content = record.get("content") if isinstance(record, dict) else None
                if content and content.get("id") == decision_id:
                    return from_dict_safe(DecisionLog, content)

            return None

        except Exception as e:
            log_debug(f"DecisionLogStore.get failed: {e}")
            return None

    async def aget(self, decision_id: str) -> Optional[DecisionLog]:
        """Async version of get."""
        if not self.db:
            return None

        try:
            # Get learnings and filter by decision_id in content
            if isinstance(self.db, AsyncBaseDb):
                results = await self.db.get_learnings(
                    learning_type=self.learning_type,
                    limit=100,
                )
            else:
                results = self.db.get_learnings(
                    learning_type=self.learning_type,
                    limit=100,
                )

            if not results:
                return None

            for record in results:
                content = record.get("content") if isinstance(record, dict) else None
                if content and content.get("id") == decision_id:
                    return from_dict_safe(DecisionLog, content)

            return None

        except Exception as e:
            log_debug(f"DecisionLogStore.aget failed: {e}")
            return None

    # =========================================================================
    # Write Operations
    # =========================================================================

    def save(self, decision: DecisionLog) -> None:
        """Save a decision to the database."""
        if not self.db or not decision:
            return

        try:
            content = to_dict_safe(decision)
            if not content:
                return

            self.db.upsert_learning(
                id=decision.id,
                learning_type=self.learning_type,
                agent_id=decision.agent_id,
                session_id=decision.session_id,
                user_id=decision.user_id,
                team_id=decision.team_id,
                content=content,
            )

            self.decisions_updated = True
            log_debug(f"DecisionLogStore.save: saved decision {decision.id}")

        except Exception as e:
            log_debug(f"DecisionLogStore.save failed: {e}")

    async def asave(self, decision: DecisionLog) -> None:
        """Async version of save."""
        if not self.db or not decision:
            return

        try:
            content = to_dict_safe(decision)
            if not content:
                return

            if isinstance(self.db, AsyncBaseDb):
                await self.db.upsert_learning(
                    id=decision.id,
                    learning_type=self.learning_type,
                    agent_id=decision.agent_id,
                    session_id=decision.session_id,
                    user_id=decision.user_id,
                    team_id=decision.team_id,
                    content=content,
                )
            else:
                self.db.upsert_learning(
                    id=decision.id,
                    learning_type=self.learning_type,
                    agent_id=decision.agent_id,
                    session_id=decision.session_id,
                    user_id=decision.user_id,
                    team_id=decision.team_id,
                    content=content,
                )

            self.decisions_updated = True
            log_debug(f"DecisionLogStore.asave: saved decision {decision.id}")

        except Exception as e:
            log_debug(f"DecisionLogStore.asave failed: {e}")

    def update_outcome(
        self,
        decision_id: str,
        outcome: str,
        outcome_quality: Optional[str] = None,
    ) -> bool:
        """Update a decision with its outcome."""
        decision = self.get(decision_id=decision_id)
        if not decision:
            return False

        decision.outcome = outcome
        decision.outcome_quality = outcome_quality
        decision.updated_at = datetime.utcnow().isoformat()

        self.save(decision=decision)
        return True

    async def aupdate_outcome(
        self,
        decision_id: str,
        outcome: str,
        outcome_quality: Optional[str] = None,
    ) -> bool:
        """Async version of update_outcome."""
        decision = await self.aget(decision_id=decision_id)
        if not decision:
            return False

        decision.outcome = outcome
        decision.outcome_quality = outcome_quality
        decision.updated_at = datetime.utcnow().isoformat()

        await self.asave(decision=decision)
        return True

    # =========================================================================
    # Extraction (ALWAYS mode)
    # =========================================================================

    def _extract_decisions_from_messages(
        self,
        messages: List["Message"],
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Extract decisions from tool calls in messages."""
        for msg in messages:
            if not hasattr(msg, "tool_calls") or not msg.tool_calls:
                continue

            for tool_call in msg.tool_calls:
                tool_name = getattr(tool_call, "name", None) or getattr(
                    getattr(tool_call, "function", None), "name", None
                )

                if not tool_name:
                    continue

                decision_id = f"dec_{uuid.uuid4().hex[:8]}"
                decision = DecisionLog(
                    id=decision_id,
                    decision=f"Called tool: {tool_name}",
                    decision_type="tool_selection",
                    context="During conversation with user",
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    created_at=datetime.utcnow().isoformat(),
                )

                self.save(decision=decision)

    async def _aextract_decisions_from_messages(
        self,
        messages: List["Message"],
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of _extract_decisions_from_messages."""
        for msg in messages:
            if not hasattr(msg, "tool_calls") or not msg.tool_calls:
                continue

            for tool_call in msg.tool_calls:
                tool_name = getattr(tool_call, "name", None) or getattr(
                    getattr(tool_call, "function", None), "name", None
                )

                if not tool_name:
                    continue

                decision_id = f"dec_{uuid.uuid4().hex[:8]}"
                decision = DecisionLog(
                    id=decision_id,
                    decision=f"Called tool: {tool_name}",
                    decision_type="tool_selection",
                    context="During conversation with user",
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    created_at=datetime.utcnow().isoformat(),
                )

                await self.asave(decision=decision)

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        has_db = self.db is not None
        has_model = self.model is not None
        return (
            f"DecisionLogStore("
            f"mode={self.config.mode.value}, "
            f"db={has_db}, "
            f"model={has_model}, "
            f"enable_agent_tools={self.config.enable_agent_tools})"
        )

    def print(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 10,
        *,
        raw: bool = False,
    ) -> None:
        """Print formatted decision log.

        Args:
            agent_id: Filter by agent.
            session_id: Filter by session.
            limit: Maximum decisions to show.
            raw: If True, print raw dict using pprint.
        """
        from agno.learn.utils import print_panel

        decisions = self.search(
            agent_id=agent_id,
            session_id=session_id,
            limit=limit,
        )

        lines = []
        for d in decisions:
            lines.append(f"[{d.id}] {d.decision}")
            if d.reasoning:
                lines.append(f"  Reasoning: {d.reasoning}")
            if d.outcome:
                lines.append(f"  Outcome: {d.outcome}")
            lines.append("")

        subtitle = agent_id or session_id or "all"

        print_panel(
            title="Decision Log",
            subtitle=subtitle,
            lines=lines,
            empty_message="No decisions logged",
            raw_data=decisions,
            raw=raw,
        )
