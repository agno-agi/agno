"""Run-local reference evidence for page-storage knowledge."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Optional

from agno.models.message import Message
from agno.utils.bounded import BoundedWorkers
from agno.utils.callables import get_resolved_knowledge
from agno.utils.message import get_text_from_message

CALLBACK_WORKERS = BoundedWorkers(8, "knowledge-context")


def page_knowledge(agent: Any, run_context: Any = None) -> bool:
    from agno.knowledge.knowledge import Knowledge

    knowledge = get_resolved_knowledge(agent, run_context)
    return isinstance(knowledge, Knowledge) and knowledge.page_store is not None


def _query(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Message):
        value = value.content
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return "\n".join(value).strip()[:500]
    if isinstance(value, list):
        questions = [
            item
            for item in value
            if (isinstance(item, Message) and item.role == "user")
            or (isinstance(item, dict) and item.get("role") == "user")
        ]
        if questions:
            return _query(questions[-1])
    return get_text_from_message(value).strip()[:500]


def _arguments(agent: Any, run_context: Any, query: str, asynchronous: bool):
    knowledge = get_resolved_knowledge(agent, run_context)
    callback = agent.knowledge_retriever
    if not callable(callback):
        callback = getattr(knowledge, "aretrieve" if asynchronous else "retrieve", None)
        if not callable(callback):
            callback = getattr(knowledge, "retrieve", None)
        arguments = {
            "query": query,
            "max_results": knowledge.max_results,
            "context_max_bytes": 24000,
            "timeout_seconds": 2,
            "filters": getattr(run_context, "knowledge_filters", None),
            "user_id": getattr(run_context, "user_id", None),
        }
    else:
        arguments = {
            "query": query,
            "num_documents": knowledge.max_results,
            "agent": agent,
            "run_context": run_context,
            "dependencies": getattr(run_context, "dependencies", None),
            "filters": getattr(run_context, "knowledge_filters", None),
            "user_id": getattr(run_context, "user_id", None),
        }
    if not callable(callback):
        return None, {}
    parameters = inspect.signature(callback).parameters
    if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        arguments = {k: v for k, v in arguments.items() if k in parameters}
    return callback, arguments


def _render(documents: Any, *, unavailable: bool = False) -> Optional[Message]:
    if documents is None and not unavailable:
        return None
    records: list[Any] = []
    omitted = 0
    status = "unavailable" if unavailable else "available" if documents else "empty"

    def content() -> str:
        data = {
            "schema_version": 1,
            "availability": status,
            "references": records,
            "truncated": omitted > 0,
            "omitted_count": omitted,
        }
        return (
            "<knowledge_references>\n"
            + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            + "\n</knowledge_references>"
        )

    if documents is not None:
        for document in documents[:100]:
            item = document.to_dict() if callable(getattr(document, "to_dict", None)) else document
            if not isinstance(item, (dict, str)):
                omitted += 1
                continue
            records.append(item)
            if len(content().encode("utf-8")) > 24000:
                records.pop()
                omitted += 1
        omitted += max(0, len(documents) - 100)
    while records and len(content().encode("utf-8")) > 24000:
        records.pop()
        omitted += 1
    return Message(role="user", name="knowledge_references", content=content(), add_to_history=False)


def _invoke(callback: Any, arguments: Any, *, budget: Any):
    budget.remaining()
    result = callback(**arguments)
    if inspect.isawaitable(result):

        async def await_result():
            return await result

        result = asyncio.run(await_result())
    budget.remaining()
    return result


def reference(agent: Any, run_context: Any, value: Any) -> Optional[Message]:
    if not agent.add_knowledge_to_context or not page_knowledge(agent, run_context):
        return None
    if getattr(run_context, "_page_reference_ready", False):
        return getattr(run_context, "_page_reference", None)
    query = _query(value)
    result = None
    if query:
        callback, arguments = _arguments(agent, run_context, query, False)
        try:
            result = _render(CALLBACK_WORKERS.run_sync(_invoke, callback, arguments, seconds=2)) if callback else None
        except Exception:
            result = _render(None, unavailable=True)
    run_context._page_reference_ready = True
    run_context._page_reference = result
    return result


async def areference(agent: Any, run_context: Any, value: Any) -> Optional[Message]:
    if not agent.add_knowledge_to_context or not page_knowledge(agent, run_context):
        return None
    if getattr(run_context, "_page_reference_ready", False):
        return getattr(run_context, "_page_reference", None)
    query = _query(value)
    result = None
    if query:
        callback, arguments = _arguments(agent, run_context, query, True)
        try:
            if callback and inspect.iscoroutinefunction(callback):
                documents = await asyncio.wait_for(callback(**arguments), timeout=2)
            elif callback:
                documents = await CALLBACK_WORKERS.run(_invoke, callback, arguments, seconds=2)
            else:
                documents = None
            result = _render(documents)
        except Exception:
            result = _render(None, unavailable=True)
    run_context._page_reference_ready = True
    run_context._page_reference = result
    return result


def _resume_input(run_response: Any, run_messages: Any) -> Any:
    original = getattr(run_response, "input", None)
    return original.input_content if original is not None else run_messages.user_message


def _insert(run_messages: Any, evidence: Optional[Message]) -> None:
    if evidence is None or any(
        m.name == "knowledge_references" and not m.add_to_history for m in run_messages.messages
    ):
        return
    # Insert before the original user question, never inside a tool call/result exchange.
    user = run_messages.user_message
    position = next((i for i, m in enumerate(run_messages.messages) if m is user), None)
    if position is None:
        position = next(
            (i for i in reversed(range(len(run_messages.messages))) if run_messages.messages[i].role == "user"),
            len(run_messages.messages),
        )
    run_messages.messages.insert(position, evidence)


def resume_references(agent: Any, run_context: Any, run_response: Any, run_messages: Any) -> None:
    from agno.run.cancel import raise_if_cancelled

    raise_if_cancelled(run_response.run_id)
    if any(tool.confirmed is False for tool in run_response.tools or []):
        return
    run_context.messages = run_messages.messages
    _insert(run_messages, reference(agent, run_context, _resume_input(run_response, run_messages)))


async def aresume_references(agent: Any, run_context: Any, run_response: Any, run_messages: Any) -> None:
    from agno.run.cancel import araise_if_cancelled

    await araise_if_cancelled(run_response.run_id)
    if any(tool.confirmed is False for tool in run_response.tools or []):
        return
    run_context.messages = run_messages.messages
    _insert(run_messages, await areference(agent, run_context, _resume_input(run_response, run_messages)))


def append_page_tools(
    roster: Any, knowledge: Any, owner: Any, run_context: Any, custom_search: Any, async_mode: bool
) -> None:
    tools = knowledge.get_tools(
        run_context=run_context, agent=owner, async_mode=async_mode, knowledge_filters=run_context.knowledge_filters
    )
    if owner.knowledge_retriever is not None:
        # A custom retriever still owns semantic search in tools-only mode.
        # Use the same signature adaptation and deadline as initial references.
        def search_knowledge(query: str) -> str:
            """Search documentation with the configured custom retriever."""
            callback, arguments = _arguments(owner, run_context, _query(query), False)
            try:
                evidence = _render(CALLBACK_WORKERS.run_sync(_invoke, callback, arguments, seconds=2))
            except Exception:
                evidence = _render(None, unavailable=True)
            return str(evidence.content).split("\n", 1)[1] if evidence is not None else '{"results":[]}'

        async def asearch_knowledge(query: str) -> str:
            """Search documentation with the configured custom retriever."""
            callback, arguments = _arguments(owner, run_context, _query(query), True)
            try:
                if inspect.iscoroutinefunction(callback):
                    documents = await asyncio.wait_for(callback(**arguments), timeout=2)
                else:
                    documents = await CALLBACK_WORKERS.run(_invoke, callback, arguments, seconds=2)
                evidence = _render(documents)
            except Exception:
                evidence = _render(None, unavailable=True)
            return str(evidence.content).split("\n", 1)[1] if evidence is not None else '{"results":[]}'

        asearch_knowledge.__name__ = "search_knowledge"
        tools = [asearch_knowledge if async_mode else search_knowledge, *tools[1:]]
    names = set()
    for tool in [*roster, *tools]:
        nested = getattr(tool, "functions", None)
        tool_names = (
            list(nested)
            if isinstance(nested, dict)
            else [getattr(tool, "name", None) or getattr(tool, "__name__", None)]
        )
        for name in tool_names:
            if name is not None and name in names:
                raise ValueError("Duplicate knowledge tool name: " + name)
            if name is not None:
                names.add(name)
    roster.extend(tools)
