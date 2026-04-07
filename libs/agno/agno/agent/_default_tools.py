"""Built-in tool factory functions for Agent."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Union,
    cast,
)

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.culture.manager import CultureManager
from agno.db.base import BaseDb, SessionType
from agno.filters import FilterExpr
from agno.knowledge.types import KnowledgeFilter
from agno.memory import MemoryManager
from agno.models.message import Message, MessageReferences
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.tools.function import Function
from agno.utils.knowledge import get_agentic_or_user_search_filters
from agno.utils.log import (
    log_debug,
    log_info,
    log_warning,
)
from agno.utils.timer import Timer


def get_update_user_memory_function(agent: Agent, user_id: Optional[str] = None, async_mode: bool = False) -> Function:
    def update_user_memory(task: str) -> str:
        """Use this function to submit a task to modify the Agent's memory.
        Describe the task in detail and be specific.
        The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

        Args:
            task: The task to update the memory. Be specific and describe the task in detail.

        Returns:
            str: A string indicating the status of the task.
        """
        agent.memory_manager = cast(MemoryManager, agent.memory_manager)
        response = agent.memory_manager.update_memory_task(task=task, user_id=user_id)

        return response

    async def aupdate_user_memory(task: str) -> str:
        """Use this function to update the Agent's memory of a user.
        Describe the task in detail and be specific.
        The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

        Args:
            task: The task to update the memory. Be specific and describe the task in detail.

        Returns:
            str: A string indicating the status of the task.
        """
        agent.memory_manager = cast(MemoryManager, agent.memory_manager)
        response = await agent.memory_manager.aupdate_memory_task(task=task, user_id=user_id)
        return response

    if async_mode:
        update_user_memory_function = aupdate_user_memory
    else:
        update_user_memory_function = update_user_memory  # type: ignore

    return Function.from_callable(update_user_memory_function, name="update_user_memory")


def get_update_cultural_knowledge_function(agent: Agent, async_mode: bool = False) -> Function:
    def update_cultural_knowledge(task: str) -> str:
        """Use this function to update a cultural knowledge."""
        agent.culture_manager = cast(CultureManager, agent.culture_manager)
        response = agent.culture_manager.update_culture_task(task=task)

        return response

    async def aupdate_cultural_knowledge(task: str) -> str:
        """Use this function to update a cultural knowledge asynchronously."""
        agent.culture_manager = cast(CultureManager, agent.culture_manager)
        response = await agent.culture_manager.aupdate_culture_task(task=task)
        return response

    if async_mode:
        update_cultural_knowledge_function = aupdate_cultural_knowledge
    else:
        update_cultural_knowledge_function = update_cultural_knowledge  # type: ignore

    return Function.from_callable(
        update_cultural_knowledge_function,
        name="create_or_update_cultural_knowledge",
    )


def create_knowledge_search_tool(
    agent: Agent,
    run_response: Optional[RunOutput] = None,
    run_context: Optional[RunContext] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    enable_agentic_filters: Optional[bool] = False,
    async_mode: bool = False,
) -> Function:
    """Create a unified search_knowledge_base tool.

    Routes all knowledge searches through get_relevant_docs_from_knowledge(),
    which checks knowledge_retriever first and falls back to knowledge.search().
    This ensures the custom retriever is always respected when provided.
    """

    def _format_results(docs: Optional[List[Union[Dict[str, Any], str]]]) -> str:
        if not docs:
            return "No documents found"
        if agent.references_format == "json":
            import json

            return json.dumps(docs, indent=2, default=str)
        else:
            import yaml

            return yaml.dump(docs, default_flow_style=False)

    def _track_references(docs: Optional[List[Union[Dict[str, Any], str]]], query: str, elapsed: float) -> None:
        if run_response is not None and docs:
            references = MessageReferences(
                query=query,
                references=docs,
                time=round(elapsed, 4),
            )
            if run_response.references is None:
                run_response.references = []
            run_response.references.append(references)

    def _resolve_filters(
        agentic_filters: Optional[List[Any]] = None,
    ) -> Optional[Union[Dict[str, Any], List[FilterExpr]]]:
        if agentic_filters:
            filters_dict: Dict[str, Any] = {}
            for filt in agentic_filters:
                if isinstance(filt, dict):
                    filters_dict.update(filt)
                elif hasattr(filt, "key") and hasattr(filt, "value"):
                    filters_dict[filt.key] = filt.value
            return get_agentic_or_user_search_filters(filters_dict, knowledge_filters)
        return knowledge_filters

    if enable_agentic_filters:

        def search_knowledge_base_with_filters(query: str, filters: Optional[List[KnowledgeFilter]] = None) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.
                filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                from agno.agent import _messages

                docs = _messages.get_relevant_docs_from_knowledge(
                    agent,
                    query=query,
                    filters=_resolve_filters(filters),
                    validate_filters=True,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        async def asearch_knowledge_base_with_filters(
            query: str, filters: Optional[List[KnowledgeFilter]] = None
        ) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.
                filters (optional): The filters to apply to the search. This is a list of KnowledgeFilter objects.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                from agno.agent import _messages

                docs = await _messages.aget_relevant_docs_from_knowledge(
                    agent,
                    query=query,
                    filters=_resolve_filters(filters),
                    validate_filters=True,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        if async_mode:
            return Function.from_callable(asearch_knowledge_base_with_filters, name="search_knowledge_base")
        return Function.from_callable(search_knowledge_base_with_filters, name="search_knowledge_base")

    else:

        def search_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                from agno.agent import _messages

                docs = _messages.get_relevant_docs_from_knowledge(
                    agent,
                    query=query,
                    filters=knowledge_filters,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        async def asearch_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            retrieval_timer = Timer()
            retrieval_timer.start()
            try:
                from agno.agent import _messages

                docs = await _messages.aget_relevant_docs_from_knowledge(
                    agent,
                    query=query,
                    filters=knowledge_filters,
                    run_context=run_context,
                )
            except Exception as e:
                log_warning(f"Knowledge search failed: {e}")
                return f"Error searching knowledge base: {type(e).__name__}"
            _track_references(docs, query, retrieval_timer.elapsed)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")
            return _format_results(docs)

        if async_mode:
            return Function.from_callable(asearch_knowledge_base, name="search_knowledge_base")
        return Function.from_callable(search_knowledge_base, name="search_knowledge_base")


def get_chat_history_function(agent: Agent, session: AgentSession) -> Callable:
    def get_chat_history(num_chats: Optional[int] = None) -> str:
        """Use this function to get the chat history between the user and agent.

        Args:
            num_chats: The number of chats to return.
                Each chat contains 2 messages. One from the user and one from the agent.
                Default: None

        Returns:
            str: A JSON of a list of dictionaries representing the chat history.

        Example:
            - To get the last chat, use num_chats=1.
            - To get the last 5 chats, use num_chats=5.
            - To get all chats, use num_chats=None.
            - To get the first chat, use num_chats=None and pick the first message.
        """
        import json

        history: List[Dict[str, Any]] = []
        all_chats = session.get_messages()

        if len(all_chats) == 0:
            return json.dumps([])

        for chat in all_chats:  # type: ignore
            history.append(chat.to_dict())  # type: ignore

        if num_chats is not None:
            history = history[-num_chats:]

        return json.dumps(history)

    return get_chat_history


def get_tool_call_history_function(agent: Agent, session: AgentSession) -> Callable:
    def get_tool_call_history(num_calls: int = 3) -> str:
        """Use this function to get the tools called by the agent in reverse chronological order.

        Args:
            num_calls: The number of tool calls to return.
                Default: 3

        Returns:
            str: A JSON of a list of dictionaries representing the tool call history.

        Example:
            - To get the last tool call, use num_calls=1.
            - To get all tool calls, use num_calls=None.
        """
        import json

        tool_calls = session.get_tool_calls(num_calls=num_calls)
        if len(tool_calls) == 0:
            return json.dumps([])
        return json.dumps(tool_calls)

    return get_tool_call_history


def update_session_state_tool(agent: Agent, run_context: RunContext, session_state_updates: dict) -> str:
    """
    Update the shared session state.  Provide any updates as a dictionary of key-value pairs.
    Example:
        "session_state_updates": {"shopping_list": ["milk", "eggs", "bread"]}

    Args:
        session_state_updates (dict): The updates to apply to the shared session state. Should be a dictionary of key-value pairs.
    """

    if run_context.session_state is None:
        run_context.session_state = {}
    session_state = run_context.session_state
    for key, value in session_state_updates.items():
        session_state[key] = value

    return f"Updated session state: {session_state}"


def make_update_session_state_entrypoint(agent: Agent) -> Callable:
    """Create a closure that binds agent to the update_session_state_tool function."""

    def _entrypoint(run_context: RunContext, session_state_updates: dict) -> str:
        """
        Update the shared session state.  Provide any updates as a dictionary of key-value pairs.
        Example:
            "session_state_updates": {"shopping_list": ["milk", "eggs", "bread"]}

        Args:
            session_state_updates (dict): The updates to apply to the shared session state. Should be a dictionary of key-value pairs.
        """
        return update_session_state_tool(agent, run_context, session_state_updates)

    return _entrypoint


def add_to_knowledge(agent: Agent, query: str, result: str) -> str:
    """Use this function to add information to the knowledge base for future use.

    Args:
        query (str): The query or topic to add.
        result (str): The actual content or information to store.
    Returns:
        str: A string indicating the status of the addition.
    """
    import json

    if agent.knowledge is None:
        return "Knowledge not available"

    # Check if knowledge supports insert
    insert_fn = getattr(agent.knowledge, "insert", None)
    if not callable(insert_fn):
        return "Knowledge does not support insert"

    document_name = query.replace(" ", "_").replace("?", "").replace("!", "").replace(".", "")
    document_content = json.dumps({"query": query, "result": result})
    log_info(f"Adding document to Knowledge: {document_name}: {document_content}")
    from agno.knowledge.reader.text_reader import TextReader

    insert_fn(name=document_name, text_content=document_content, reader=TextReader())
    return "Successfully added to knowledge base"


def _get_message_text(msg: Message) -> Optional[str]:
    """Safely extract text content from a Message."""
    if isinstance(msg.content, str):
        return msg.content
    if isinstance(msg.content, list):
        parts = []
        for part in msg.content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
        return " ".join(parts) if parts else None
    return None


def _truncate(text: str, limit: int = 200) -> str:
    """Truncate text to *limit* characters, appending '...' if trimmed."""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _extract_session_preview(session: Union[AgentSession, Any], num_runs: int = 3) -> Dict[str, Any]:
    """Extract session_id, created_at, and per-run user/assistant previews."""
    runs_preview: List[Dict[str, str]] = []
    for run in (session.runs or [])[:num_runs]:
        user_text = ""
        assistant_text = ""
        for msg in run.messages or []:
            if msg.role == "user" and not user_text:
                text = _get_message_text(msg)
                if text:
                    user_text = _truncate(text)
            elif msg.role == "assistant" and not assistant_text:
                text = _get_message_text(msg)
                if text:
                    assistant_text = _truncate(text)
            if user_text and assistant_text:
                break
        if user_text or assistant_text:
            runs_preview.append({"user": user_text, "assistant": assistant_text})
    return {
        "session_id": session.session_id,
        "created_at": str(session.created_at) if session.created_at else None,
        "runs": runs_preview,
    }


def get_search_past_sessions_function(
    agent: Agent,
    num_past_sessions_to_search: Optional[int] = None,
    num_past_session_runs_in_search: Optional[int] = None,
    user_id: Optional[str] = None,
    current_session_id: Optional[str] = None,
) -> Callable:
    """Factory for search_past_sessions tool."""

    _limit = num_past_sessions_to_search if num_past_sessions_to_search is not None else 20
    _num_runs = num_past_session_runs_in_search if num_past_session_runs_in_search is not None else 3

    def search_past_sessions() -> str:
        """List previous chat sessions with short previews.
        Use read_past_session to read the full conversation for a specific session.

        Returns:
            str: JSON list of session previews with session_id, created_at, and runs (user/assistant pairs).
        """
        import json

        if agent.db is None:
            return json.dumps([])

        agent.db = cast(BaseDb, agent.db)
        selected_sessions = agent.db.get_sessions(
            session_type=SessionType.AGENT,
            limit=_limit,
            user_id=user_id,
            sort_by="created_at",
            sort_order="desc",
        )

        results: List[Dict[str, Any]] = []
        for session in selected_sessions:
            if not isinstance(session, AgentSession) or not session.runs:
                continue
            if current_session_id and session.session_id == current_session_id:
                continue
            results.append(_extract_session_preview(session, num_runs=_num_runs))

        return json.dumps(results)

    return search_past_sessions


async def aget_search_past_sessions_function(
    agent: Agent,
    num_past_sessions_to_search: Optional[int] = None,
    num_past_session_runs_in_search: Optional[int] = None,
    user_id: Optional[str] = None,
    current_session_id: Optional[str] = None,
) -> Function:
    """Async factory for search_past_sessions tool."""
    from agno.agent import _init

    _limit = num_past_sessions_to_search if num_past_sessions_to_search is not None else 20
    _num_runs = num_past_session_runs_in_search if num_past_session_runs_in_search is not None else 3

    async def search_past_sessions() -> str:
        """List previous chat sessions with short previews.
        Use read_past_session to read the full conversation for a specific session.

        Returns:
            str: JSON list of session previews with session_id, created_at, and runs (user/assistant pairs).
        """
        import json

        if agent.db is None:
            return json.dumps([])

        if _init.has_async_db(agent):
            selected_sessions = await agent.db.get_sessions(  # type: ignore
                session_type=SessionType.AGENT,
                limit=_limit,
                user_id=user_id,
                sort_by="created_at",
                sort_order="desc",
            )
        else:
            selected_sessions = agent.db.get_sessions(
                session_type=SessionType.AGENT,
                limit=_limit,
                user_id=user_id,
                sort_by="created_at",
                sort_order="desc",
            )

        results: List[Dict[str, Any]] = []
        for session in selected_sessions:  # type: ignore
            if not isinstance(session, AgentSession) or not session.runs:
                continue
            if current_session_id and session.session_id == current_session_id:
                continue
            results.append(_extract_session_preview(session, num_runs=_num_runs))

        return json.dumps(results)

    return Function.from_callable(search_past_sessions, name="search_past_sessions")


def get_read_past_session_function(
    agent: Agent,
    user_id: Optional[str] = None,
) -> Callable:
    """Factory for read_past_session tool."""

    def read_past_session(session_id: str, num_runs: Optional[int] = None) -> str:
        """Read the full conversation from a previous session.
        Use search_past_sessions first to find relevant sessions.

        Args:
            session_id: The session ID to read (from search results).
            num_runs: Maximum number of runs to include. Default: all runs.

        Returns:
            str: The conversation formatted as User/Assistant message pairs.
        """
        if agent.db is None:
            return "No database configured."

        agent.db = cast(BaseDb, agent.db)
        session = agent.db.get_session(
            session_id=session_id,
            session_type=SessionType.AGENT,
            user_id=user_id,
        )

        if session is None or not isinstance(session, AgentSession) or not session.runs:
            return "Session not found."

        lines: List[str] = []
        lines.append(f"Session: {session.session_id}")
        if session.created_at:
            lines.append(f"Created: {session.created_at}")
        lines.append("")

        runs = session.runs if num_runs is None else session.runs[:num_runs]
        for run in runs:
            for msg in run.messages or []:
                if msg.role not in ("user", "assistant"):
                    continue
                text = _get_message_text(msg)
                if text:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    lines.append(f"{role_label}: {text}")
                    lines.append("")

        return "\n".join(lines) if lines else "No messages found in session."

    return read_past_session


async def aget_read_past_session_function(
    agent: Agent,
    user_id: Optional[str] = None,
) -> Function:
    """Async factory for read_past_session tool."""
    from agno.agent import _init

    async def read_past_session(session_id: str, num_runs: Optional[int] = None) -> str:
        """Read the full conversation from a previous session.
        Use search_past_sessions first to find relevant sessions.

        Args:
            session_id: The session ID to read (from search results).
            num_runs: Maximum number of runs to include. Default: all runs.

        Returns:
            str: The conversation formatted as User/Assistant message pairs.
        """
        if agent.db is None:
            return "No database configured."

        if _init.has_async_db(agent):
            session = await agent.db.get_session(  # type: ignore
                session_id=session_id,
                session_type=SessionType.AGENT,
                user_id=user_id,
            )
        else:
            session = agent.db.get_session(  # type: ignore
                session_id=session_id,
                session_type=SessionType.AGENT,
                user_id=user_id,
            )

        if session is None or not isinstance(session, AgentSession) or not session.runs:
            return "Session not found."

        lines: List[str] = []
        lines.append(f"Session: {session.session_id}")
        if session.created_at:
            lines.append(f"Created: {session.created_at}")
        lines.append("")

        runs = session.runs if num_runs is None else session.runs[:num_runs]
        for run in runs:
            for msg in run.messages or []:
                if msg.role not in ("user", "assistant"):
                    continue
                text = _get_message_text(msg)
                if text:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    lines.append(f"{role_label}: {text}")
                    lines.append("")

        return "\n".join(lines) if lines else "No messages found in session."

    return Function.from_callable(read_past_session, name="read_past_session")
