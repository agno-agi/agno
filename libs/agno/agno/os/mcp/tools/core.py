"""Core MCP tools for AgentOS."""

from typing import TYPE_CHECKING, List, Optional, Union, cast

from fastmcp import Context, FastMCP
from packaging import version

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.db.migrations.manager import MigrationManager
from agno.os.mcp.auth import get_user_id_from_context, require_resource_access
from agno.os.schema import (
    AgentSummaryResponse,
    ConfigResponse,
    InterfaceResponse,
    Model,
    TeamSummaryResponse,
    WorkflowSummaryResponse,
)
from agno.os.utils import get_agent_by_id, get_db, get_team_by_id, get_workflow_by_id
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.team.team import Team

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_core_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register core MCP tools for AgentOS configuration and operations."""

    @mcp.tool(
        name="get_agentos_config",
        description="Get the configuration of the AgentOS",
        tags={"core"},
    )  # type: ignore
    async def get_agentos_config() -> ConfigResponse:
        return ConfigResponse(
            name=os.name or "AgentOS",
            os_id=os.id or "AgentOS",
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            databases=[db.id for db_list in os.dbs.values() for db in db_list],
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
            traces=os._get_traces_config(),
            agents=[AgentSummaryResponse.from_agent(agent) for agent in os.agents] if os.agents else [],
            teams=[TeamSummaryResponse.from_team(team) for team in os.teams] if os.teams else [],
            workflows=[WorkflowSummaryResponse.from_workflow(w) for w in os.workflows] if os.workflows else [],
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.prefix)
                for interface in os.interfaces
            ],
        )

    @mcp.tool(
        name="get_models",
        description="Get a list of all unique models currently used by agents and teams in this OS instance",
        tags={"core"},
    )  # type: ignore
    async def get_models() -> List[Model]:
        all_components: List[Union[Agent, Team]] = []
        if os.agents:
            all_components.extend(os.agents)
        if os.teams:
            all_components.extend(os.teams)

        unique_models = {}
        for item in all_components:
            model = cast(Model, item.model)
            if model.id is not None and model.provider is not None:
                key = (model.id, model.provider)
                if key not in unique_models:
                    unique_models[key] = Model(id=model.id, provider=model.provider)

        return list(unique_models.values())

    @mcp.tool(
        name="migrate_database",
        description="Migrate the given database schema to the given target version. If target_version is not provided, migrates to the latest version.",
        tags={"core"},
    )  # type: ignore
    async def migrate_database(db_id: str, target_version: Optional[str] = None) -> dict:
        db = await get_db(os.dbs, db_id)
        if not db:
            raise Exception(f"Database {db_id} not found")

        if target_version:
            if isinstance(db, AsyncBaseDb):
                current_version = await db.get_latest_schema_version(db.session_table_name)
            else:
                current_version = db.get_latest_schema_version(db.session_table_name)

            if version.parse(target_version) > version.parse(current_version):  # type: ignore
                MigrationManager(db).up(target_version)  # type: ignore
            else:
                MigrationManager(db).down(target_version)  # type: ignore
        else:
            MigrationManager(db).up()  # type: ignore

        return {"message": f"Database migrated successfully to version {target_version or 'latest'}"}

    @mcp.tool(
        name="run_agent",
        description="Run an agent with a message and get the response",
        tags={"core"},
    )  # type: ignore
    async def run_agent(
        ctx: Context,
        agent_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RunOutput:
        # Check access permission
        require_resource_access(ctx, agent_id, "agents")

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise Exception(f"Agent {agent_id} not found")

        # Use user_id from context if not provided
        if user_id is None:
            user_id = get_user_id_from_context(ctx)

        return await agent.arun(message, session_id=session_id, user_id=user_id)

    @mcp.tool(
        name="run_team",
        description="Run a team with a message and get the response",
        tags={"core"},
    )  # type: ignore
    async def run_team(
        ctx: Context,
        team_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> TeamRunOutput:
        # Check access permission
        require_resource_access(ctx, team_id, "teams")

        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise Exception(f"Team {team_id} not found")

        # Use user_id from context if not provided
        if user_id is None:
            user_id = get_user_id_from_context(ctx)

        return await team.arun(message, session_id=session_id, user_id=user_id)

    @mcp.tool(
        name="run_workflow",
        description="Run a workflow with a message and get the response",
        tags={"core"},
    )  # type: ignore
    async def run_workflow(
        ctx: Context,
        workflow_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> WorkflowRunOutput:
        # Check access permission
        require_resource_access(ctx, workflow_id, "workflows")

        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise Exception(f"Workflow {workflow_id} not found")

        # Use user_id from context if not provided
        if user_id is None:
            user_id = get_user_id_from_context(ctx)

        return await workflow.arun(message, session_id=session_id, user_id=user_id)
