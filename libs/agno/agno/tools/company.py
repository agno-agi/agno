"""Bounded Company tools for agents and direct MCP calls.

Identity is injected by the framework. No tool can accept or complete work,
reassign ownership, edit a Product brief, or change local Sources. Human chats
may create Products and Routines under the caller's permissions.
"""

import asyncio
import json
from dataclasses import asdict
from typing import Annotated, Any, Dict, List, Optional
from uuid import uuid4
from weakref import ReferenceType

from pydantic import BeforeValidator

from agno.company.declarations import Product, Routine, Source
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _require_routine_product, _RoutineAuthorization
from agno.company.sources import is_remote_git
from agno.db.base import AsyncBaseDb
from agno.run.authorization import current_authorization, requires_permission
from agno.tools import Toolkit


def _empty_to_none(value: Any) -> Any:
    """Treat a model's empty optional argument as omitted, preserving other values."""
    return None if value == "" else value


def _public_source(source: Dict[str, Any]) -> Dict[str, Any]:
    """Describe supported operations without exposing credentials or probing the Source."""
    remote_git = is_remote_git(source)
    return {
        **{key: value for key, value in source.items() if key != "credential_ref"},
        "readable": not remote_git,
        "checkout_supported": remote_git,
    }


# Keep nullable schemas and normalize empty strings before Pydantic validation.
_OptionalString = Annotated[Optional[str], BeforeValidator(_empty_to_none)]
_OptionalInt = Annotated[Optional[int], BeforeValidator(_empty_to_none)]
_OptionalSourceConfig = Annotated[Optional[Dict[str, List[str]]], BeforeValidator(_empty_to_none)]


def _authority(run_context):
    return current_authorization() or getattr(run_context, "authorization", None)


def _identity(run_context):
    authority = _authority(run_context)
    return authority.context.principal_id if authority is not None else getattr(run_context, "user_id", None)


def _permission(resource, action, run_context):
    authority = _authority(run_context)
    if authority is not None:
        authority.require(resource, action)


async def _apermission(resource, action, run_context):
    authority = _authority(run_context)
    if authority is not None:
        await authority.arequire(resource, action)


def _require_plain_proposal(run_context):
    from agno.company.routines import _RoutineAuthorization

    if isinstance(_authority(run_context), _RoutineAuthorization):
        raise PermissionError(
            "Routines must propose Tasks through intake_product_source with evidence and a dedupe key"
        )


def _require_human_creation(run_context):
    from agno.company.execution import _automatic_task, _ExecutorAuthorization
    from agno.os.auth import INTERNAL_SCHEDULER_USER_ID

    authority = _authority(run_context)
    if isinstance(authority, _ExecutorAuthorization) or _automatic_task.get() is not None:
        raise PermissionError(
            "Company Products and Routines cannot be created from automated runs; Routines propose work"
        )
    if (authority is not None and authority.service_account) or _identity(run_context) == INTERNAL_SCHEDULER_USER_ID:
        raise PermissionError("Only a calling human may create Company Products and Routines from chat")


def _automated_edit_stage(row, run_context):
    """Return "backlog" for automated callers, raising if the Task has left it; None for humans."""
    from agno.company.execution import _automatic_task, _ExecutorAuthorization

    if not (isinstance(_authority(run_context), _ExecutorAuthorization) or _automatic_task.get() is not None):
        return None
    if row["status"] != "backlog":
        raise PermissionError("Automated runs may edit Task content only in Backlog")
    return "backlog"


def _require_edited(edited, stage):
    if edited is None and stage is not None:
        raise PermissionError(
            "Task changed before the automated edit; automated runs edit Task content only in Backlog"
        )
    return edited


def _chat_sources(sources, agent, team, run_context):
    from agno.company.manager import _validate_agent_source

    executor = team if team is not None else agent
    for source in sources:
        if source.id or source.credential_ref:
            raise ValueError("Chat website Sources cannot set id or credential_ref; add them through the Source API")
        _validate_agent_source(
            source.type,
            "team" if team is not None else "agent",
            getattr(executor, "id", None),
            getattr(run_context, "run_id", None),
        )


def _routine_declaration(name, executor_type, executor_id, template, instructions, cron_expr, timezone):
    return Routine.model_validate(
        dict(
            name=name,
            executor_type=executor_type,
            executor_id=executor_id,
            template=_empty_to_none(template),
            instructions=_empty_to_none(instructions),
            cron_expr=_empty_to_none(cron_expr),
            timezone=_empty_to_none(timezone) or "UTC",
        )
    )


def _page(result, limit, page):
    rows, total = result
    from agno.db.schemas.tasks import public_task

    rows = [public_task(row) if isinstance(row, dict) and "transitions" in row else row for row in rows]
    return _public_json(
        {
            "data": rows,
            "meta": {"page": page, "limit": limit, "total_count": total, "total_pages": (total + limit - 1) // limit},
        },
        default=str,
    )


class CompanyTools(Toolkit):
    """Company-wide reads and proposal-only writes, following StudioTools injection.

    user_isolation is deployment configuration, never an argument offered to a
    model. Like HTTP, service accounts remain scoped even with isolation off.
    """

    def __init__(
        self,
        db: Any,
        *,
        user_isolation: bool = False,
        decision_tools: bool = True,
        summary_tools: bool = True,
        refresh_tools: bool = True,
        agent_id: Optional[str] = None,
        interfaces: Any = None,
        registry: Any = None,
    ):
        self._interfaces_explicit = interfaces is not None
        self.interfaces = interfaces if interfaces is not None else []
        self._automation_history_retention_days = 30
        self._schedule_db = db
        self._agent_os_ref: Optional[ReferenceType[Any]] = None
        self.db = db
        self.registry = registry
        self.user_isolation = user_isolation
        # Supplied by the learning machine, never by the model or an MCP argument.
        self._agent_id = agent_id
        names = [
            "list_product_sources",
            "add_product_source",
            "read_product_source",
            "intake_product_source",
            "create_company_product",
            "create_product_routine",
            "list_company_products",
            "get_company_product",
            "list_company_projects",
            "list_company_tasks",
            "propose_company_project",
            "propose_company_task",
            "edit_company_project",
            "edit_company_task",
            "list_company_wiki",
            "read_company_wiki",
            "update_product_status",
        ]
        if decision_tools:
            names += ["log_company_decision", "search_company_decisions"]
        if summary_tools:
            names += ["summarize_company_product"]
        if refresh_tools:
            names += ["refresh_company_product"]
        super().__init__(
            name="company",
            tools=[getattr(self, name) for name in names],
            async_tools=[(getattr(self, "a" + name), name) for name in names],
        )

    def _scoped_user(self, run_context):
        user = _identity(run_context)
        authority = _authority(run_context)
        if authority is not None:
            ctx = authority.context
            if (authority.service_account or authority.provider.enforces_token_scopes) and (
                (ctx.admin_scope or "agent_os:admin") in ctx.scopes
            ):
                return None
        if self.user_isolation or (isinstance(user, str) and user.startswith("sa:")):
            if not user:
                if isinstance(authority, _RoutineAuthorization) and authority.original is None:
                    # An unowned Routine fires unscoped like any unowned schedule, still bound to its Product.
                    return None
                raise PermissionError("Caller identity is required under user isolation")
            return user
        return None

    def _sync(self):
        if isinstance(self.db, AsyncBaseDb):
            raise TypeError("Use async Company tools with an asynchronous database")
        return CompanyManager(
            self.db,
            registry=self.registry,
            schedule_db=self._schedule_db,
            automation_history_retention_days=self._automation_history_retention_days,
        )

    def _async(self):
        if isinstance(self.db, AsyncBaseDb):
            return AsyncCompanyManager(
                self.db,
                registry=self.registry,
                schedule_db=self._schedule_db,
                automation_history_retention_days=self._automation_history_retention_days,
            )
        return _AsyncSyncManager(
            CompanyManager(
                self.db,
                registry=self.registry,
                schedule_db=self._schedule_db,
                automation_history_retention_days=self._automation_history_retention_days,
            )
        )

    def _declare_product(self, name, purpose, sources, routines, agent, team, run_context):
        from agno.db.schemas.products import validate_product_fields

        product = Product(name=name, purpose=_empty_to_none(purpose), sources=sources or [], routines=routines or [])
        validate_product_fields({"name": product.name, "purpose": product.purpose})
        if len({routine.name for routine in product.routines}) != len(product.routines):
            raise ValueError("Routine names must be unique within a Product")
        _chat_sources(product.sources, agent, team, run_context)
        return product

    def _routine_check(self, routine, run_context):
        """Chat-side checks on the composed schedule; the manager runs them before any write."""
        from agno.tools.scheduler import _manager_member_refusal, archived_endpoint_refusal

        def check(fields):
            refusal = _manager_member_refusal(fields["endpoint"])
            if refusal:
                raise ValueError(refusal)
            authority = _authority(run_context)
            if authority is not None:
                authority.require(routine.executor_type + "s", "run", routine.executor_id)
            if archived_endpoint_refusal(self._schedule_db, fields["endpoint"], user_id=self._scoped_user(run_context)):
                raise ValueError("Routine executor is archived; restore the component first")

        return check

    def _aroutine_check(self, routine, run_context):
        from agno.tools.scheduler import _manager_member_refusal, aarchived_endpoint_refusal

        async def check(fields):
            refusal = _manager_member_refusal(fields["endpoint"])
            if refusal:
                raise ValueError(refusal)
            authority = _authority(run_context)
            if authority is not None:
                await authority.arequire(routine.executor_type + "s", "run", routine.executor_id)
            if await aarchived_endpoint_refusal(
                self._schedule_db, fields["endpoint"], user_id=self._scoped_user(run_context)
            ):
                raise ValueError("Routine executor is archived; restore the component first")

        return check

    @requires_permission()
    def create_company_product(
        self,
        name: str,
        purpose: _OptionalString = None,
        sources: Annotated[Optional[List[Source]], BeforeValidator(_empty_to_none)] = None,
        routines: Annotated[Optional[List[Routine]], BeforeValidator(_empty_to_none)] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Create a Product for the calling human, optionally with website Sources and Routines.

        Args:
            purpose: Product purpose; null leaves it unspecified.
            sources: Source declarations as in config; null adds no Sources. Websites only.
            routines: Routine declarations as in config; null adds no Routines.
        """
        from agno.company.routines import _declared_schedule_fields

        _require_human_creation(_agno_run_context)
        _permission("products", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        product = self._declare_product(name, purpose, sources, routines, _agno_agent, _agno_team, _agno_run_context)
        if product.sources:
            _permission("sources", "write", _agno_run_context)
        if product.routines:
            _permission("schedules", "write", _agno_run_context)
            _permission("routines", "write", _agno_run_context)
        # The id is chosen first so every Routine is checked under its real schedule name before any write.
        product_id = str(uuid4())
        plans = []
        for routine in product.routines:
            fields = _declared_schedule_fields(
                product_id, routine, self.registry, agent_os=self._agent_os_ref() if self._agent_os_ref else None
            )
            self._routine_check(routine, _agno_run_context)(fields)
            plans.append((routine, fields))
        manager = self._sync()
        identity = _identity(_agno_run_context)
        manager.create(id=product_id, name=product.name, purpose=product.purpose, user_id=identity)
        source_ids: List[str] = []
        schedule_ids: List[str] = []
        try:
            for source in product.sources:
                row = self.add_product_source(
                    product_id,
                    source.reference,
                    config=source.config,
                    _agno_agent=_agno_agent,
                    _agno_team=_agno_team,
                    _agno_run_context=_agno_run_context,
                )
                source_ids.append(json.loads(row)["id"])
            for routine, fields in plans:
                schedule_ids.append(manager._write_routine(product_id, routine, fields, identity)["id"])
        except Exception:
            manager.discard_product(product_id, source_ids=source_ids, schedule_ids=schedule_ids, user_id=identity)
            raise
        return _public_json(manager.get(product_id))

    @requires_permission()
    def create_product_routine(
        self,
        product_id: str,
        name: str,
        executor_type: str,
        executor_id: str,
        template: _OptionalString = None,
        instructions: _OptionalString = None,
        cron_expr: _OptionalString = None,
        timezone: _OptionalString = "UTC",
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Create a Routine for the calling human; automated runs cannot create Routines.

        Args:
            template: Optional intake, refresh or summary template; null requires instructions.
            instructions: Custom instructions; null uses the selected template.
            cron_expr: Cron expression; null creates an on-demand Routine.
            timezone: Schedule timezone; null uses UTC.
        """
        _require_human_creation(_agno_run_context)
        _permission("products", "write", _agno_run_context)
        _permission("schedules", "write", _agno_run_context)
        _permission("routines", "write", _agno_run_context)
        routine = _routine_declaration(name, executor_type, executor_id, template, instructions, cron_expr, timezone)
        return _public_json(
            self._sync().create_routine(
                product_id=product_id,
                routine=routine,
                user_id=_identity(_agno_run_context),
                scoped_user_id=self._scoped_user(_agno_run_context),
                check=self._routine_check(routine, _agno_run_context),
                agent_os=self._agent_os_ref() if self._agent_os_ref else None,
            )
        )

    @requires_permission()
    async def acreate_company_product(
        self,
        name: str,
        purpose: _OptionalString = None,
        sources: Annotated[Optional[List[Source]], BeforeValidator(_empty_to_none)] = None,
        routines: Annotated[Optional[List[Routine]], BeforeValidator(_empty_to_none)] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Create a Product for the calling human, optionally with website Sources and Routines.

        Args:
            purpose: Product purpose; null leaves it unspecified.
            sources: Source declarations as in config; null adds no Sources. Websites only.
            routines: Routine declarations as in config; null adds no Routines.
        """
        from agno.company.routines import _declared_schedule_fields

        _require_human_creation(_agno_run_context)
        await _apermission("products", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        product = self._declare_product(name, purpose, sources, routines, _agno_agent, _agno_team, _agno_run_context)
        if product.sources:
            await _apermission("sources", "write", _agno_run_context)
        if product.routines:
            await _apermission("schedules", "write", _agno_run_context)
            await _apermission("routines", "write", _agno_run_context)
        # The id is chosen first so every Routine is checked under its real schedule name before any write.
        product_id = str(uuid4())
        plans = []
        for routine in product.routines:
            fields = _declared_schedule_fields(
                product_id, routine, self.registry, agent_os=self._agent_os_ref() if self._agent_os_ref else None
            )
            await self._aroutine_check(routine, _agno_run_context)(fields)
            plans.append((routine, fields))
        manager = self._async()
        identity = _identity(_agno_run_context)
        await manager.create(id=product_id, name=product.name, purpose=product.purpose, user_id=identity)
        source_ids: List[str] = []
        schedule_ids: List[str] = []
        try:
            for source in product.sources:
                row = await self.aadd_product_source(
                    product_id,
                    source.reference,
                    config=source.config,
                    _agno_agent=_agno_agent,
                    _agno_team=_agno_team,
                    _agno_run_context=_agno_run_context,
                )
                source_ids.append(json.loads(row)["id"])
            for routine, fields in plans:
                schedule_ids.append((await manager._write_routine(product_id, routine, fields, identity))["id"])
        except Exception:
            await manager.discard_product(
                product_id, source_ids=source_ids, schedule_ids=schedule_ids, user_id=identity
            )
            raise
        return _public_json(await manager.get(product_id))

    @requires_permission()
    async def acreate_product_routine(
        self,
        product_id: str,
        name: str,
        executor_type: str,
        executor_id: str,
        template: _OptionalString = None,
        instructions: _OptionalString = None,
        cron_expr: _OptionalString = None,
        timezone: _OptionalString = "UTC",
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Create a Routine for the calling human; automated runs cannot create Routines.

        Args:
            template: Optional intake, refresh or summary template; null requires instructions.
            instructions: Custom instructions; null uses the selected template.
            cron_expr: Cron expression; null creates an on-demand Routine.
            timezone: Schedule timezone; null uses UTC.
        """
        _require_human_creation(_agno_run_context)
        await _apermission("products", "write", _agno_run_context)
        await _apermission("schedules", "write", _agno_run_context)
        await _apermission("routines", "write", _agno_run_context)
        routine = _routine_declaration(name, executor_type, executor_id, template, instructions, cron_expr, timezone)
        # A synchronous database runs the manager in a worker thread, where only a plain check can run.
        check = (
            self._aroutine_check(routine, _agno_run_context)
            if isinstance(self.db, AsyncBaseDb)
            else self._routine_check(routine, _agno_run_context)
        )
        return _public_json(
            await self._async().create_routine(
                product_id=product_id,
                routine=routine,
                user_id=_identity(_agno_run_context),
                scoped_user_id=self._scoped_user(_agno_run_context),
                check=check,
                agent_os=self._agent_os_ref() if self._agent_os_ref else None,
            )
        )

    @requires_permission()
    def list_company_products(
        self, limit: _OptionalInt = 20, page: _OptionalInt = 1, _agno_run_context: Optional[Any] = None
    ) -> str:
        """List every Product in the company.

        Args:
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        _permission("products", "read", _agno_run_context)
        return _page(self._sync().list(limit=limit, page=page), limit, page)

    @requires_permission()
    def get_company_product(self, product_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Product's purpose and current configuration."""
        _permission("products", "read", _agno_run_context)
        product = self._sync().get(product_id)
        if product is None:
            raise LookupError("Product not found")
        return _public_json(product)

    @requires_permission()
    def list_company_projects(
        self,
        product_id: _OptionalString = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """List proposed and active Projects across owners.

        Args:
            product_id: Product ID; null includes all Products.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        product_id = _empty_to_none(product_id)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        _permission("projects", "read", _agno_run_context)
        return _page(self._sync().list_projects(product_id=product_id, limit=limit, page=page), limit, page)

    @requires_permission()
    def list_company_tasks(
        self,
        product_id: _OptionalString = None,
        status: _OptionalString = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """List Tasks across owners, optionally filtered by status.

        Args:
            product_id: Product ID; null includes all Products.
            status: Task status to filter by; null includes all statuses.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        product_id = _empty_to_none(product_id)
        status = _empty_to_none(status)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        _permission("tasks", "read", _agno_run_context)
        return _page(self._sync().list_tasks(product_id=product_id, status=status, limit=limit, page=page), limit, page)

    @requires_permission()
    def propose_company_project(
        self, product_id: str, name: str, outcome: _OptionalString = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Propose a Project for human review; never activate or complete it.

        Args:
            outcome: Expected or observed outcome; null leaves it unspecified.
        """
        outcome = _empty_to_none(outcome)
        _permission("projects", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        return _public_json(
            self._sync().create_project(
                product_id=product_id, name=name, outcome=outcome, user_id=_identity(_agno_run_context)
            )
        )

    @requires_permission()
    def propose_company_task(
        self,
        product_id: str,
        title: str,
        brief: _OptionalString = None,
        project_id: _OptionalString = None,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Create a Backlog proposal with an optional suggested executor; never accept work.

        Args:
            executor_type: Suggested executor kind; null leaves selection to acceptance.
            executor_id: Suggested executor ID; null leaves selection to acceptance.
            brief: Task brief; null leaves it unspecified.
            project_id: Required Project ID within the Product. Propose a Project first when none fits.
        """
        executor_type = _empty_to_none(executor_type)
        executor_id = _empty_to_none(executor_id)
        brief = _empty_to_none(brief)
        project_id = _empty_to_none(project_id)
        if not project_id:
            raise ValueError("A Task requires a Project")
        _require_plain_proposal(_agno_run_context)
        _permission("tasks", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        return _public_json(
            self._sync().create_task(
                product_id=product_id,
                title=title,
                brief=brief,
                project_id=project_id,
                user_id=_identity(_agno_run_context),
                origin="routine" if getattr(_authority(_agno_run_context), "routine_id", None) else "product_manager",
                routine_id=getattr(_authority(_agno_run_context), "routine_id", None),
                executor_type=executor_type,
                executor_id=executor_id,
            )
        )

    @requires_permission()
    def edit_company_project(
        self, project_id: str, name: str, outcome: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Edit a proposed Project; accepted work stays frozen."""
        _permission("projects", "write", _agno_run_context)
        manager = self._sync()
        row = manager.get_project(project_id)
        if row is None:
            raise LookupError("Project not found")
        self._scoped_user(_agno_run_context)
        _require_routine_product(row["product_id"])
        if row["status"] != "proposed":
            raise ValueError("Only proposed Projects may be edited by Company tools")
        return _public_json(
            manager.update_project(project_id, user_id=None, expected_status="proposed", name=name, outcome=outcome)
        )

    @requires_permission()
    def edit_company_task(self, task_id: str, title: str, brief: str, _agno_run_context: Optional[Any] = None) -> str:
        """Edit a Task's title and brief; automated runs only in Backlog. Never changes lifecycle, executor or ownership."""
        _permission("tasks", "write", _agno_run_context)
        manager = self._sync()
        row = manager.get_task(task_id)
        if row is None:
            raise LookupError("Task not found")
        self._scoped_user(_agno_run_context)
        _require_routine_product(row["product_id"])
        stage = _automated_edit_stage(row, _agno_run_context)
        edited = manager.update_task(task_id, user_id=None, expected_status=stage, title=title, brief=brief)
        return _public_json(_require_edited(edited, stage))

    @requires_permission()
    def list_company_wiki(
        self,
        product_id: _OptionalString = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """List the Product playbook, or the company playbook when product_id is omitted.

        Args:
            product_id: Product ID; null selects the company playbook.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        product_id = _empty_to_none(product_id)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        _permission("wiki", "read", _agno_run_context)
        rows, total = self._sync().list_wiki(product_id, limit=limit, page=page)
        return _page(([asdict(row) for row in rows], total), limit, page)

    @requires_permission()
    def read_company_wiki(
        self, path: str, product_id: _OptionalString = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Read a playbook page and its version before planning or editing.

        Args:
            product_id: Product ID; null selects the company playbook.
        """
        product_id = _empty_to_none(product_id)
        _permission("wiki", "read", _agno_run_context)
        return _public_json(asdict(self._sync().read_wiki(product_id, path)))

    @requires_permission()
    def update_product_status(
        self, product_id: str, content: str, expected_version: int, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Update status.md after reading it; supply the version read to prevent lost edits."""
        _permission("wiki", "write", _agno_run_context)
        return _public_json(
            asdict(
                self._sync().write_wiki(
                    product_id=product_id,
                    path="status.md",
                    content=content,
                    expected_version=expected_version,
                    user_id=self._scoped_user(_agno_run_context),
                )
            )
        )

    @requires_permission()
    def log_company_decision(
        self,
        decision: str,
        reasoning: _OptionalString = None,
        context: _OptionalString = None,
        outcome: _OptionalString = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Append a decision with reasoning, context and observed outcome to the learning log.

        Args:
            reasoning: Reason for the decision; null leaves it unspecified.
            context: Decision context; null leaves it unspecified.
            outcome: Expected or observed outcome; null leaves it unspecified.
        """
        reasoning = _empty_to_none(reasoning)
        context = _empty_to_none(context)
        outcome = _empty_to_none(outcome)
        _permission("decisions", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        return _public_json(
            asdict(
                self._sync().log_decision(
                    decision=decision,
                    reasoning=reasoning,
                    context=context,
                    outcome=outcome,
                    user_id=_identity(_agno_run_context),
                    session_id=getattr(_agno_run_context, "session_id", None),
                    agent_id=self._agent_id,
                )
            )
        )

    @requires_permission()
    def search_company_decisions(
        self,
        query: _OptionalString = None,
        agent_id: _OptionalString = None,
        session_id: _OptionalString = None,
        days: _OptionalInt = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Search the company decision log by text, agent, session or age.

        Args:
            query: Text to search for; null includes all decision text.
            agent_id: Agent ID to filter by; null includes all agents.
            session_id: Session ID to filter by; null includes all sessions.
            days: Maximum age in days; null applies no age filter.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        query = _empty_to_none(query)
        agent_id = _empty_to_none(agent_id)
        session_id = _empty_to_none(session_id)
        days = _empty_to_none(days)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        _permission("decisions", "read", _agno_run_context)
        rows, total = self._sync().list_decisions(query, agent_id, session_id, days, limit, page)
        return _page(([asdict(row) for row in rows], total), limit, page)

    @requires_permission()
    async def alist_company_products(
        self, limit: _OptionalInt = 20, page: _OptionalInt = 1, _agno_run_context: Optional[Any] = None
    ) -> str:
        """List every Product in the company.

        Args:
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        await _apermission("products", "read", _agno_run_context)
        return _page(await self._async().list(limit=limit, page=page), limit, page)

    @requires_permission()
    async def aget_company_product(self, product_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Product's purpose and current configuration."""
        await _apermission("products", "read", _agno_run_context)
        product = await self._async().get(product_id)
        if product is None:
            raise LookupError("Product not found")
        return _public_json(product)

    @requires_permission()
    async def alist_company_projects(
        self,
        product_id: _OptionalString = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """List proposed and active Projects across owners.

        Args:
            product_id: Product ID; null includes all Products.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        product_id = _empty_to_none(product_id)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        await _apermission("projects", "read", _agno_run_context)
        return _page(await self._async().list_projects(product_id=product_id, limit=limit, page=page), limit, page)

    @requires_permission()
    async def alist_company_tasks(
        self,
        product_id: _OptionalString = None,
        status: _OptionalString = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """List Tasks across owners, optionally filtered by status.

        Args:
            product_id: Product ID; null includes all Products.
            status: Task status to filter by; null includes all statuses.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        product_id = _empty_to_none(product_id)
        status = _empty_to_none(status)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        await _apermission("tasks", "read", _agno_run_context)
        return _page(
            await self._async().list_tasks(product_id=product_id, status=status, limit=limit, page=page), limit, page
        )

    @requires_permission()
    async def apropose_company_project(
        self, product_id: str, name: str, outcome: _OptionalString = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Propose a Project for human review; never activate or complete it.

        Args:
            outcome: Expected or observed outcome; null leaves it unspecified.
        """
        outcome = _empty_to_none(outcome)
        await _apermission("projects", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        return _public_json(
            await self._async().create_project(
                product_id=product_id, name=name, outcome=outcome, user_id=_identity(_agno_run_context)
            )
        )

    @requires_permission()
    async def apropose_company_task(
        self,
        product_id: str,
        title: str,
        brief: _OptionalString = None,
        project_id: _OptionalString = None,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Create a Backlog proposal with an optional suggested executor; never accept work.

        Args:
            executor_type: Suggested executor kind; null leaves selection to acceptance.
            executor_id: Suggested executor ID; null leaves selection to acceptance.
            brief: Task brief; null leaves it unspecified.
            project_id: Required Project ID within the Product. Propose a Project first when none fits.
        """
        executor_type = _empty_to_none(executor_type)
        executor_id = _empty_to_none(executor_id)
        brief = _empty_to_none(brief)
        project_id = _empty_to_none(project_id)
        if not project_id:
            raise ValueError("A Task requires a Project")
        _require_plain_proposal(_agno_run_context)
        await _apermission("tasks", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        return _public_json(
            await self._async().create_task(
                product_id=product_id,
                title=title,
                brief=brief,
                project_id=project_id,
                user_id=_identity(_agno_run_context),
                origin="routine" if getattr(_authority(_agno_run_context), "routine_id", None) else "product_manager",
                routine_id=getattr(_authority(_agno_run_context), "routine_id", None),
                executor_type=executor_type,
                executor_id=executor_id,
            )
        )

    @requires_permission()
    async def aedit_company_project(
        self, project_id: str, name: str, outcome: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Edit a proposed Project; accepted work stays frozen."""
        await _apermission("projects", "write", _agno_run_context)
        manager = self._async()
        row = await manager.get_project(project_id)
        if row is None:
            raise LookupError("Project not found")
        self._scoped_user(_agno_run_context)
        _require_routine_product(row["product_id"])
        if row["status"] != "proposed":
            raise ValueError("Only proposed Projects may be edited by Company tools")
        return _public_json(
            await manager.update_project(
                project_id, user_id=None, expected_status="proposed", name=name, outcome=outcome
            )
        )

    @requires_permission()
    async def aedit_company_task(
        self, task_id: str, title: str, brief: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Edit a Task's title and brief; automated runs only in Backlog. Never changes lifecycle, executor or ownership."""
        await _apermission("tasks", "write", _agno_run_context)
        manager = self._async()
        row = await manager.get_task(task_id)
        if row is None:
            raise LookupError("Task not found")
        self._scoped_user(_agno_run_context)
        _require_routine_product(row["product_id"])
        stage = _automated_edit_stage(row, _agno_run_context)
        edited = await manager.update_task(task_id, user_id=None, expected_status=stage, title=title, brief=brief)
        return _public_json(_require_edited(edited, stage))

    @requires_permission()
    async def alist_company_wiki(
        self,
        product_id: _OptionalString = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """List the Product playbook, or the company playbook when product_id is omitted.

        Args:
            product_id: Product ID; null selects the company playbook.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        product_id = _empty_to_none(product_id)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        await _apermission("wiki", "read", _agno_run_context)
        rows, total = await self._async().list_wiki(product_id, limit=limit, page=page)
        return _page(([asdict(row) for row in rows], total), limit, page)

    @requires_permission()
    async def aread_company_wiki(
        self, path: str, product_id: _OptionalString = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Read a playbook page and its version before planning or editing.

        Args:
            product_id: Product ID; null selects the company playbook.
        """
        product_id = _empty_to_none(product_id)
        await _apermission("wiki", "read", _agno_run_context)
        return _public_json(asdict(await self._async().read_wiki(product_id, path)))

    @requires_permission()
    async def aupdate_product_status(
        self, product_id: str, content: str, expected_version: int, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Update status.md after reading it; supply the version read to prevent lost edits."""
        await _apermission("wiki", "write", _agno_run_context)
        return _public_json(
            asdict(
                await self._async().write_wiki(
                    product_id=product_id,
                    path="status.md",
                    content=content,
                    expected_version=expected_version,
                    user_id=self._scoped_user(_agno_run_context),
                )
            )
        )

    @requires_permission()
    async def alog_company_decision(
        self,
        decision: str,
        reasoning: _OptionalString = None,
        context: _OptionalString = None,
        outcome: _OptionalString = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Append a decision with reasoning, context and observed outcome to the learning log.

        Args:
            reasoning: Reason for the decision; null leaves it unspecified.
            context: Decision context; null leaves it unspecified.
            outcome: Expected or observed outcome; null leaves it unspecified.
        """
        reasoning = _empty_to_none(reasoning)
        context = _empty_to_none(context)
        outcome = _empty_to_none(outcome)
        await _apermission("decisions", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        return _public_json(
            asdict(
                await self._async().log_decision(
                    decision=decision,
                    reasoning=reasoning,
                    context=context,
                    outcome=outcome,
                    user_id=_identity(_agno_run_context),
                    session_id=getattr(_agno_run_context, "session_id", None),
                    agent_id=self._agent_id,
                )
            )
        )

    @requires_permission()
    async def asearch_company_decisions(
        self,
        query: _OptionalString = None,
        agent_id: _OptionalString = None,
        session_id: _OptionalString = None,
        days: _OptionalInt = None,
        limit: _OptionalInt = 20,
        page: _OptionalInt = 1,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Search the company decision log by text, agent, session or age.

        Args:
            query: Text to search for; null includes all decision text.
            agent_id: Agent ID to filter by; null includes all agents.
            session_id: Session ID to filter by; null includes all sessions.
            days: Maximum age in days; null applies no age filter.
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        query = _empty_to_none(query)
        agent_id = _empty_to_none(agent_id)
        session_id = _empty_to_none(session_id)
        days = _empty_to_none(days)
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        await _apermission("decisions", "read", _agno_run_context)
        rows, total = await self._async().list_decisions(query, agent_id, session_id, days, limit, page)
        return _page(([asdict(row) for row in rows], total), limit, page)

    def _source_context(self, source_id, run_context):
        if run_context is None or not getattr(run_context, "run_id", None):
            raise ValueError("Source tools require the injected run context")
        return run_context.run_id

    @requires_permission()
    def add_product_source(
        self,
        product_id: str,
        reference: str,
        config: _OptionalSourceConfig = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Save a discovered website Source. Local Sources must be added by a human.

        Identical additions return the existing Source; conflicting settings are refused.

        Args:
            config: Optional reader settings; null uses the default configuration.
        """
        _permission("sources", "write", _agno_run_context)
        config = _empty_to_none(config)
        row = self._sync().add_source(
            product_id=product_id,
            type="website",
            reference=reference,
            executor_id=getattr(_agno_team if _agno_team is not None else _agno_agent, "id", None),
            executor_type="team" if _agno_team is not None else "agent",
            run_id=getattr(_agno_run_context, "run_id", None),
            config=config,
            user_id=_identity(_agno_run_context),
            scoped_user_id=self._scoped_user(_agno_run_context),
        )
        return json.dumps({key: value for key, value in row.items() if key != "credential_ref"}, default=str)

    @requires_permission()
    def list_product_sources(
        self, product_id: str, limit: _OptionalInt = 20, page: _OptionalInt = 1, _agno_run_context: Optional[Any] = None
    ) -> str:
        """List Product Sources and their supported operations.

        readable means read_product_source and intake_product_source support this
        Source: websites, Markdown and local Git paths. checkout_supported marks
        Git URLs used for sandbox checkout and publication; they cannot be read.
        These flags describe capabilities, not current availability or authorization.

        Args:
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        _permission("sources", "read", _agno_run_context)
        rows, total = self._sync().list_sources(product_id=product_id, limit=limit, page=page)
        return _page(
            ([_public_source(row) for row in rows], total),
            limit,
            page,
        )

    @requires_permission()
    def read_product_source(
        self,
        source_id: str,
        path: _OptionalString = None,
        pattern: _OptionalString = None,
        offset: _OptionalInt = 0,
        limit: _OptionalInt = 20,
        content_offset: _OptionalInt = 0,
        max_chars: _OptionalInt = 8000,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Discover Source files, then read selected content within a bounded response.

        Select a Source marked readable by list_product_sources. Git URL Sources
        support sandbox checkout/publication only; use a local repository Source
        to read code.

        Omit path for a content-free index; pattern filters filenames with a glob.
        Page with offset/limit (1..100) and next_offset. Pass a returned path to
        read one document: max_chars (1..16000) caps content, next_content_offset
        continues it. content_hash identifies the full reader document; compare
        hashes across fragments and reread if changed. Every response is at most
        64 KiB. Intake accepts only observed links and their full content hashes.

        Args:
            path: Selected document path; null returns the file index.
            pattern: Filename glob for discovery; null includes all configured files.
            offset: Zero-based index offset; null uses 0.
            limit: Index page size from 1 to 100; null uses 20.
            content_offset: Zero-based content character offset; null uses 0.
            max_chars: Content character cap from 1 to 16000; null uses 8000.
        """
        path = _empty_to_none(path)
        pattern = _empty_to_none(pattern)
        offset = _empty_to_none(offset)
        offset = 0 if offset is None else offset
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        content_offset = _empty_to_none(content_offset)
        content_offset = 0 if content_offset is None else content_offset
        max_chars = _empty_to_none(max_chars)
        max_chars = 8000 if max_chars is None else max_chars
        _permission("sources", "read", _agno_run_context)
        run_id = self._source_context(source_id, _agno_run_context)
        return _public_json(
            self._sync().browse_source(source_id, run_id, path, pattern, offset, limit, content_offset, max_chars)
        )

    @requires_permission()
    def intake_product_source(
        self,
        source_id: str,
        title: str,
        brief: str,
        proposal_key: str,
        evidence_links: List[str],
        evidence_hashes: Dict[str, str],
        _agno_run_context: Optional[Any] = None,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        project_id: _OptionalString = None,
    ) -> str:
        """Propose actionable work backed by selected Source links.

        Read the Source first. Use a stable proposal_key for the same issue across
        scans and edits, and a concise outcome and brief, not copied file content.
        Pass evidence_hashes mapping each selected link to its observed content_hash.
        Changed evidence is rejected: read again and reconsider the proposal.

        Args:
            executor_type: Suggested executor kind; null leaves selection to acceptance.
            executor_id: Suggested executor ID; null leaves selection to acceptance.
            project_id: Required Project ID within the Product. Propose a Project first when none fits.
        """
        executor_type = _empty_to_none(executor_type)
        executor_id = _empty_to_none(executor_id)
        project_id = _empty_to_none(project_id)
        if not project_id:
            raise ValueError("A Task requires a Project")
        _permission("sources", "read", _agno_run_context)
        _permission("tasks", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        run_id = self._source_context(source_id, _agno_run_context)
        return _public_json(
            self._sync().intake(
                source_id=source_id,
                run_id=run_id,
                proposal={
                    "title": title,
                    "brief": brief,
                    "proposal_key": proposal_key,
                    "evidence_links": evidence_links,
                    "evidence_hashes": evidence_hashes,
                },
                user_id=_identity(_agno_run_context),
                routine_id=getattr(_authority(_agno_run_context), "routine_id", None),
                executor_type=executor_type,
                executor_id=executor_id,
                project_id=project_id,
            )
        )

    @requires_permission()
    def refresh_company_product(self, product_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Propose Project completion and archive old terminal work using the Product's window."""
        from agno.company.routines import _RoutineAuthorization

        if not isinstance(_authority(_agno_run_context), _RoutineAuthorization):
            raise PermissionError("Refresh maintenance requires Routine authority")
        for resource, action in (
            ("products", "read"),
            ("projects", "read"),
            ("projects", "delete"),
            ("tasks", "read"),
            ("tasks", "delete"),
            ("wiki", "read"),
            ("wiki", "write"),
        ):
            _permission(resource, action, _agno_run_context)
        return json.dumps(self._sync().refresh(product_id, user_id=self._scoped_user(_agno_run_context)))

    @requires_permission()
    def summarize_company_product(
        self, product_id: str, narrative: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Deliver current work and attention counts to the configured interface and Product wiki."""
        _permission("products", "read", _agno_run_context)
        _permission("tasks", "read", _agno_run_context)
        _permission("wiki", "write", _agno_run_context)
        run_id = self._source_context(product_id, _agno_run_context)
        return _public_json(
            self._sync().summarize(
                product_id=product_id,
                run_id=run_id,
                interfaces=self.interfaces,
                narrative=narrative,
                user_id=self._scoped_user(_agno_run_context),
            )
        )

    @requires_permission()
    async def aadd_product_source(
        self,
        product_id: str,
        reference: str,
        config: _OptionalSourceConfig = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Save a discovered website Source. Local Sources must be added by a human.

        Identical additions return the existing Source; conflicting settings are refused.

        Args:
            config: Optional reader settings; null uses the default configuration.
        """
        await _apermission("sources", "write", _agno_run_context)
        config = _empty_to_none(config)
        row = await self._async().add_source(
            product_id=product_id,
            type="website",
            reference=reference,
            executor_id=getattr(_agno_team if _agno_team is not None else _agno_agent, "id", None),
            executor_type="team" if _agno_team is not None else "agent",
            run_id=getattr(_agno_run_context, "run_id", None),
            config=config,
            user_id=_identity(_agno_run_context),
            scoped_user_id=self._scoped_user(_agno_run_context),
        )
        return json.dumps({key: value for key, value in row.items() if key != "credential_ref"}, default=str)

    @requires_permission()
    async def alist_product_sources(
        self, product_id: str, limit: _OptionalInt = 20, page: _OptionalInt = 1, _agno_run_context: Optional[Any] = None
    ) -> str:
        """List Product Sources and their supported operations.

        readable means read_product_source and intake_product_source support this
        Source: websites, Markdown and local Git paths. checkout_supported marks
        Git URLs used for sandbox checkout and publication; they cannot be read.
        These flags describe capabilities, not current availability or authorization.

        Args:
            limit: Maximum results per page; null uses 20.
            page: One-based page number; null uses 1.
        """
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        page = _empty_to_none(page)
        page = 1 if page is None else page
        await _apermission("sources", "read", _agno_run_context)
        rows, total = await self._async().list_sources(product_id=product_id, limit=limit, page=page)
        return _page(
            ([_public_source(row) for row in rows], total),
            limit,
            page,
        )

    @requires_permission()
    async def aread_product_source(
        self,
        source_id: str,
        path: _OptionalString = None,
        pattern: _OptionalString = None,
        offset: _OptionalInt = 0,
        limit: _OptionalInt = 20,
        content_offset: _OptionalInt = 0,
        max_chars: _OptionalInt = 8000,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Discover Source files, then read selected content within a bounded response.

        Select a Source marked readable by list_product_sources. Git URL Sources
        support sandbox checkout/publication only; use a local repository Source
        to read code.

        Omit path for a content-free index; pattern filters filenames with a glob.
        Page with offset/limit (1..100) and next_offset. Pass a returned path to
        read one document: max_chars (1..16000) caps content, next_content_offset
        continues it. content_hash identifies the full reader document; compare
        hashes across fragments and reread if changed. Every response is at most
        64 KiB. Intake accepts only observed links and their full content hashes.

        Args:
            path: Selected document path; null returns the file index.
            pattern: Filename glob for discovery; null includes all configured files.
            offset: Zero-based index offset; null uses 0.
            limit: Index page size from 1 to 100; null uses 20.
            content_offset: Zero-based content character offset; null uses 0.
            max_chars: Content character cap from 1 to 16000; null uses 8000.
        """
        path = _empty_to_none(path)
        pattern = _empty_to_none(pattern)
        offset = _empty_to_none(offset)
        offset = 0 if offset is None else offset
        limit = _empty_to_none(limit)
        limit = 20 if limit is None else limit
        content_offset = _empty_to_none(content_offset)
        content_offset = 0 if content_offset is None else content_offset
        max_chars = _empty_to_none(max_chars)
        max_chars = 8000 if max_chars is None else max_chars
        await _apermission("sources", "read", _agno_run_context)
        run_id = self._source_context(source_id, _agno_run_context)
        return _public_json(
            await self._async().browse_source(
                source_id, run_id, path, pattern, offset, limit, content_offset, max_chars
            )
        )

    @requires_permission()
    async def aintake_product_source(
        self,
        source_id: str,
        title: str,
        brief: str,
        proposal_key: str,
        evidence_links: List[str],
        evidence_hashes: Dict[str, str],
        _agno_run_context: Optional[Any] = None,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        project_id: _OptionalString = None,
    ) -> str:
        """Propose actionable work backed by selected Source links.

        Read the Source first. Use a stable proposal_key for the same issue across
        scans and edits, and a concise outcome and brief, not copied file content.
        Pass evidence_hashes mapping each selected link to its observed content_hash.
        Changed evidence is rejected: read again and reconsider the proposal.

        Args:
            executor_type: Suggested executor kind; null leaves selection to acceptance.
            executor_id: Suggested executor ID; null leaves selection to acceptance.
            project_id: Required Project ID within the Product. Propose a Project first when none fits.
        """
        executor_type = _empty_to_none(executor_type)
        executor_id = _empty_to_none(executor_id)
        project_id = _empty_to_none(project_id)
        if not project_id:
            raise ValueError("A Task requires a Project")
        await _apermission("sources", "read", _agno_run_context)
        await _apermission("tasks", "write", _agno_run_context)
        self._scoped_user(_agno_run_context)
        run_id = self._source_context(source_id, _agno_run_context)
        return _public_json(
            await self._async().intake(
                source_id=source_id,
                run_id=run_id,
                proposal={
                    "title": title,
                    "brief": brief,
                    "proposal_key": proposal_key,
                    "evidence_links": evidence_links,
                    "evidence_hashes": evidence_hashes,
                },
                user_id=_identity(_agno_run_context),
                routine_id=getattr(_authority(_agno_run_context), "routine_id", None),
                executor_type=executor_type,
                executor_id=executor_id,
                project_id=project_id,
            )
        )

    @requires_permission()
    async def arefresh_company_product(self, product_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Propose Project completion and archive old terminal work using the Product's window."""
        from agno.company.routines import _RoutineAuthorization

        if not isinstance(_authority(_agno_run_context), _RoutineAuthorization):
            raise PermissionError("Refresh maintenance requires Routine authority")
        for resource, action in (
            ("products", "read"),
            ("projects", "read"),
            ("projects", "delete"),
            ("tasks", "read"),
            ("tasks", "delete"),
            ("wiki", "read"),
            ("wiki", "write"),
        ):
            await _apermission(resource, action, _agno_run_context)
        return json.dumps(await self._async().refresh(product_id, user_id=self._scoped_user(_agno_run_context)))

    @requires_permission()
    async def asummarize_company_product(
        self, product_id: str, narrative: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Deliver current work and attention counts to the configured interface and Product wiki."""
        await _apermission("products", "read", _agno_run_context)
        await _apermission("tasks", "read", _agno_run_context)
        await _apermission("wiki", "write", _agno_run_context)
        run_id = self._source_context(product_id, _agno_run_context)
        return _public_json(
            await self._async().summarize(
                product_id=product_id,
                run_id=run_id,
                interfaces=self.interfaces,
                narrative=narrative,
                user_id=self._scoped_user(_agno_run_context),
            )
        )


class _AsyncSyncManager:
    """Offload the existing sync service for async tool execution."""

    def __init__(self, manager):
        self.manager = manager

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            return await asyncio.to_thread(getattr(self.manager, name), *args, **kwargs)

        return call


def _public_json(value, **kwargs):
    from agno.run.authorization import AUTHORIZATION_KEY

    def clean(item):
        if isinstance(item, dict):
            return {
                key: clean(child)
                for key, child in item.items()
                if key not in {AUTHORIZATION_KEY, "_agno_company_acceptance"}
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item

    return json.dumps(clean(value), **kwargs)
