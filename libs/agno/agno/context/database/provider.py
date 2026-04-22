"""
Database Context Provider
=========================

A namespaced read/write surface over any SQL database. Two tools:

- `query_<id>` — natural-language reads, backed by a sub-agent bound
                 to a readonly engine.
- `update_<id>` — natural-language writes, backed by a sub-agent bound
                  to a writable engine.

Two sub-agents so the read path never sees the write engine. Callers
supply both engines and the schema the provider is scoped to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.sql import SQLTools

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from agno.models.base import Model


class DatabaseContextProvider(ContextProvider):
    """Read + write access to a SQL schema via two tools."""

    def __init__(
        self,
        *,
        id: str = "database",
        name: str | None = None,
        sql_engine: Engine,
        readonly_engine: Engine,
        schema: str | None = None,
        read_instructions: str | None = None,
        write_instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.sql_engine = sql_engine
        self.readonly_engine = readonly_engine
        self.schema = schema
        self.read_instructions_text = read_instructions if read_instructions is not None else DEFAULT_READ_INSTRUCTIONS
        self.write_instructions_text = (
            write_instructions if write_instructions is not None else DEFAULT_WRITE_INSTRUCTIONS
        )
        self._read_agent: Agent | None = None
        self._write_agent: Agent | None = None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Status:
        try:
            with self.readonly_engine.connect() as conn:
                if self.schema:
                    count = conn.execute(
                        text("SELECT count(*) FROM information_schema.tables WHERE table_schema = :schema"),
                        {"schema": self.schema},
                    ).scalar()
                    detail = f"{count} table(s) in {self.schema}"
                else:
                    conn.execute(text("SELECT 1"))
                    detail = "connected"
        except Exception as exc:
            return Status(ok=False, detail=f"{type(exc).__name__}: {exc}")
        return Status(ok=True, detail=detail)

    async def astatus(self) -> Status:
        return self.status()

    # ------------------------------------------------------------------
    # Query / update
    # ------------------------------------------------------------------

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_read_agent().run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_read_agent().arun(question, **kwargs))

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_write_agent().run(instruction, **kwargs))

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_write_agent().arun(instruction, **kwargs))

    def instructions(self) -> str:
        scope = f" in the `{self.schema}` schema" if self.schema else ""
        if self.mode == ContextMode.tools:
            return f"`{self.name}`: read-only `run_sql_query`{scope}. Writes require mode=default (two-tool surface)."
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to read data{scope}, "
            f"or `{self.update_tool_name}(instruction)` to modify it."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return [self._query_tool(), self._update_tool()]

    def _all_tools(self) -> list:
        # mode=tools returns only the readonly SQLTools. The read/write
        # split the default sub-agent mode provides doesn't flatten into a
        # single tool list cleanly, and silent write exposure is the wrong
        # default. Writes require mode=default (two-tool surface:
        # query_<id> / update_<id>) or explicit instantiation of a second
        # writable provider.
        return [SQLTools(db_engine=self.readonly_engine, schema=self.schema)]

    # ------------------------------------------------------------------
    # Sub-agents
    # ------------------------------------------------------------------

    def _ensure_read_agent(self) -> Agent:
        if self._read_agent is None:
            self._read_agent = self._build_read_agent()
        return self._read_agent

    def _ensure_write_agent(self) -> Agent:
        if self._write_agent is None:
            self._write_agent = self._build_write_agent()
        return self._write_agent

    def _build_read_agent(self) -> Agent:
        schema_label = self.schema or "database"
        return Agent(
            id=f"{self.id}-read",
            name=f"{self.name} Read",
            model=self.model,
            instructions=self.read_instructions_text.replace("{schema}", schema_label),
            tools=[SQLTools(db_engine=self.readonly_engine, schema=self.schema)],
            markdown=True,
        )

    def _build_write_agent(self) -> Agent:
        schema_label = self.schema or "database"
        return Agent(
            id=f"{self.id}-write",
            name=f"{self.name} Write",
            model=self.model,
            instructions=self.write_instructions_text.replace("{schema}", schema_label),
            tools=[SQLTools(db_engine=self.sql_engine, schema=self.schema)],
            markdown=True,
        )


DEFAULT_READ_INSTRUCTIONS = """\
You answer questions about data in `{schema}`.

## Workflow

1. **Introspect first** for unfamiliar requests: list tables, describe
   columns, then run a query. Don't guess at table or column names.
2. **Prefer structured output** — tables, lists, ids. Cite which
   table(s) you read. Don't invent fields.
3. **If the requested data doesn't exist, say so plainly.** Don't
   fabricate, don't paper over empty results with training knowledge.

You are read-only. Writes happen through the update tool. If the user
asks you to save or change something, explain that writes go through
the write tool and stop.
"""


DEFAULT_WRITE_INSTRUCTIONS = """\
You modify data in `{schema}`.

## Workflow

1. **Introspect before writing** when the request refers to an existing
   table: describe it, confirm the columns, then INSERT/UPDATE.
2. **DDL on demand.** If the request doesn't fit an existing table,
   CREATE a new table with sensible columns and an `id` primary key,
   then INSERT the row.
3. **Report what you did concisely, echoing the key fields** the user
   gave you. Don't recite the full row or explain the SQL you ran.
4. **DROP requires explicit user confirmation.** Don't drop tables on a
   first ask.

## Safety

Writes are scoped to the configured schema — the engine enforces this
boundary and requests outside it will error. If the user asks for a
table in another schema, explain the scope and propose an in-scope name
instead.
"""
