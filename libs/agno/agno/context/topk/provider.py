"""
TopK Context Provider
=====================

Wraps TopK Context Engine as an Agno context provider.
Exposes four tools for the calling agent:

- ``list_datasets_<id>`` — discover available datasets and their descriptions.
- ``ask_<id>(question, datasets, ...)`` — AI-synthesized answer (auto mode).
- ``search_<id>(query, datasets, ...)`` — ranked document retrieval.
- ``research_<id>(question, datasets, ...)`` — deep research pass (mode="research").

Typical agent workflow:
  1. Call ``list_datasets_<id>`` to see what datasets are available.
  2. Pick the relevant dataset(s) to query against.
  3. Call ``search``, ``ask``, or ``research`` with the chosen dataset(s).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass

import topk_sdk
import topk_sdk.error

from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Document, Status, _sanitize_id, _serialize_answer
from agno.run import RunContext
from agno.run.agent import CustomEvent
from agno.tools import tool


@dataclass
class TopKProgressEvent(CustomEvent):
    """Emitted during ask/research while TopK is processing.

    Yield from an ``async for`` loop over ``agent.arun(..., stream=True)``
    to surface real-time progress updates to the user.
    """

    update: str = ""

    def __str__(self) -> str:
        # Return empty so progress events don't pollute the tool result the LLM sees.
        return ""


class TopKContextProvider(ContextProvider):
    """TopK context engine as an Agno context provider.

    Args:
        id: Provider identifier used to namespace tools (default ``"topk"``).
        name: Display name shown in instructions.
        api_key: TopK API key (or set ``TOPK_API_KEY`` env var).
        region: TopK region (or set ``TOPK_REGION`` env var).
        host: TopK host (default ``"topk.io"``).
        mode: How a ContextProvider exposes itself to a calling agent.
    """

    def __init__(
        self,
        *,
        id: str = "topk",
        name: str = "TopK",
        api_key: str | None = None,
        region: str | None = None,
        host: str = "topk.io",
        https: bool = True,
        mode: ContextMode = ContextMode.default,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, write=False)
        self.api_key = api_key
        self.region = region
        self.host = host
        self.https = https
        self._sync_client: topk_sdk.Client | None = None
        self._async_client: topk_sdk.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Client access (lazy)
    # ------------------------------------------------------------------

    def _sync(self) -> topk_sdk.Client:
        if self._sync_client is None:
            api_key = self.api_key or os.environ.get("TOPK_API_KEY")
            region = self.region or os.environ.get("TOPK_REGION")
            if not api_key:
                raise ValueError("api_key is required or set TOPK_API_KEY env var")
            if not region:
                raise ValueError("region is required or set TOPK_REGION env var")
            self._sync_client = topk_sdk.Client(
                api_key=api_key,
                region=region,
                host=self.host,
                https=self.https,
            )
        return self._sync_client

    def _async(self) -> topk_sdk.AsyncClient:
        if self._async_client is None:
            api_key = self.api_key or os.environ.get("TOPK_API_KEY")
            region = self.region or os.environ.get("TOPK_REGION")
            if not api_key:
                raise ValueError("api_key is required or set TOPK_API_KEY env var")
            if not region:
                raise ValueError("region is required or set TOPK_REGION env var")
            self._async_client = topk_sdk.AsyncClient(
                api_key=api_key,
                region=region,
                host=self.host,
                https=self.https,
            )
        return self._async_client

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Status:
        try:
            self._sync().datasets().get(f"probe_{uuid.uuid4().hex}")
        except topk_sdk.error.DatasetNotFoundError:
            return Status(ok=True)
        except Exception as exc:
            return Status(ok=False, detail=str(exc))
        return Status(ok=True)

    async def astatus(self) -> Status:
        try:
            await self._async().datasets().get(f"probe_{uuid.uuid4().hex}")
        except topk_sdk.error.DatasetNotFoundError:
            return Status(ok=True)
        except Exception as exc:
            return Status(ok=False, detail=str(exc))
        return Status(ok=True)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        datasets = [d.name for d in self._sync().datasets().list()]
        for message in self._sync().ask(query=question, datasets=datasets):
            if isinstance(message, topk_sdk.Answer):
                return _answer_from_topk(message)
        return Answer()

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        datasets = [d.name for d in await self._async().datasets().list()]
        async for message in self._async().ask(query=question, datasets=datasets):
            if isinstance(message, topk_sdk.Answer):
                return _answer_from_topk(message)
        return Answer()

    # ------------------------------------------------------------------
    # Instructions for the calling agent
    # ------------------------------------------------------------------

    def instructions(self) -> str:
        sid = _sanitize_id(self.id)
        return (
            f"`{self.name}`:\n"
            f"- `list_datasets_{sid}()` — discover available datasets and what they contain.\n"
            f"- `search_{sid}(query, datasets)` — ranked document retrieval from chosen datasets.\n"
            f"- `ask_{sid}(question, datasets)` — synthesized answer (auto mode).\n"
            f"- `research_{sid}(question, datasets)` — deep research pass, slower but thorough.\n"
            f"Always call `list_datasets_{sid}` first to find relevant datasets."
        )

    # ------------------------------------------------------------------
    # Tool surface
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return [self._list_datasets_tool(), self._search_tool(), self._ask_tool(), self._research_tool()]

    def _all_tools(self) -> list:
        return [self._list_datasets_tool(), self._search_tool(), self._ask_tool(), self._research_tool()]

    # ------------------------------------------------------------------
    # Individual tool builders
    # ------------------------------------------------------------------

    def _list_datasets_tool(self):
        provider = self
        safe_id = _sanitize_id(self.id)

        @tool(name=f"list_datasets_{safe_id}")
        async def _list_datasets(run_context: RunContext | None = None) -> str:
            datasets = await provider._async().datasets().list()
            return json.dumps([{"name": d.name, "description": d.description} for d in datasets])

        return _list_datasets

    def _search_tool(self):
        provider = self
        safe_id = _sanitize_id(self.id)

        @tool(name=f"search_{safe_id}")
        async def _search(
            query: str,
            datasets: list[str],
            top_k: int = 10,
            select_fields: list[str] | None = None,
            run_context: RunContext | None = None,
        ) -> str:
            results: list[Document] = []
            async for result in provider._async().search(
                query=query,
                datasets=datasets,
                top_k=top_k,
                select_fields=select_fields,
            ):
                results.append(_search_result_to_doc(result))
            return json.dumps(_serialize_answer(Answer(results=results)))

        return _search

    def _ask_tool(self):
        provider = self
        safe_id = _sanitize_id(self.id)

        @tool(name=f"ask_{safe_id}")
        async def _ask(
            question: str,
            datasets: list[str],
            select_fields: list[str] | None = None,
            run_context: RunContext | None = None,
        ):
            async for message in provider._async().ask(
                query=question,
                datasets=datasets,
                select_fields=select_fields,
            ):
                if isinstance(message, topk_sdk.Progress):
                    yield TopKProgressEvent(update=message.update)
                elif isinstance(message, topk_sdk.Answer):
                    yield json.dumps(_serialize_answer(_answer_from_topk(message)))
                    return
            yield json.dumps(_serialize_answer(Answer()))

        return _ask

    def _research_tool(self):
        provider = self
        safe_id = _sanitize_id(self.id)

        @tool(name=f"research_{safe_id}")
        async def _research(
            question: str,
            datasets: list[str],
            select_fields: list[str] | None = None,
            run_context: RunContext | None = None,
        ):
            async for message in provider._async().ask(
                query=question,
                datasets=datasets,
                mode="research",
                select_fields=select_fields,
            ):
                if isinstance(message, topk_sdk.Progress):
                    yield TopKProgressEvent(update=message.update)
                elif isinstance(message, topk_sdk.Answer):
                    yield json.dumps(_serialize_answer(_answer_from_topk(message)))
                    return
            yield json.dumps(_serialize_answer(Answer()))

        return _research


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _answer_from_topk(topk_answer: topk_sdk.Answer) -> Answer:
    text = "\n".join(f.fact for f in topk_answer.facts) if topk_answer.facts else None
    results = [_search_result_to_doc(sr) for sr in topk_answer.refs.values()]
    return Answer(text=text, results=results)


def _search_result_to_doc(result: topk_sdk.SearchResult) -> Document:
    snippet: str | None = None
    if result.content is not None:
        data = getattr(result.content, "data", None)
        if data is not None:
            snippet = getattr(data, "text", None)
    return Document(
        id=result.doc_id,
        name=result.doc_name,
        source=result.dataset,
        snippet=snippet,
    )
