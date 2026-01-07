"""Eval MCP tools for running and managing evaluations."""

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from fastmcp import FastMCP

from agno.db.base import AsyncBaseDb
from agno.db.schemas.evals import EvalType
from agno.os.routers.evals.schemas import EvalSchema
from agno.os.utils import get_agent_by_id, get_db, get_team_by_id
from agno.remote.base import RemoteDb

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_eval_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register evaluation MCP tools."""

    @mcp.tool(
        name="get_eval_runs",
        description="Get a paginated list of evaluation runs with optional filtering",
        tags={"evals"},
    )  # type: ignore
    async def get_eval_runs(
        db_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict:
        db = await get_db(os.dbs, db_id)

        # Default eval types (excluding agent-as-judge for now)
        eval_types = [EvalType.ACCURACY, EvalType.PERFORMANCE, EvalType.RELIABILITY]

        if isinstance(db, RemoteDb):
            result = await db.get_eval_runs(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                model_id=model_id,
                eval_type=eval_types,
            )
            return {
                "data": [e.model_dump() for e in result.data],
                "total_count": result.meta.total_count if result.meta else 0,
                "page": page,
                "limit": limit,
            }

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            eval_runs, total_count = await db.get_eval_runs(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                model_id=model_id,
                eval_type=eval_types,
                deserialize=False,
            )
        else:
            eval_runs, total_count = db.get_eval_runs(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                model_id=model_id,
                eval_type=eval_types,
                deserialize=False,
            )

        return {
            "data": [EvalSchema.from_dict(run).model_dump() for run in eval_runs],  # type: ignore
            "total_count": total_count,
            "page": page,
            "limit": limit,
        }

    @mcp.tool(
        name="get_eval_run",
        description="Get detailed results for a specific evaluation run",
        tags={"evals"},
    )  # type: ignore
    async def get_eval_run(eval_run_id: str, db_id: Optional[str] = None) -> dict:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            result = await db.get_eval_run(eval_run_id=eval_run_id)
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            eval_run = await db.get_eval_run(eval_run_id=eval_run_id, deserialize=False)
        else:
            eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False)

        if not eval_run:
            raise Exception(f"Eval run {eval_run_id} not found")

        return EvalSchema.from_dict(eval_run).model_dump()  # type: ignore

    @mcp.tool(
        name="delete_eval_runs",
        description="Delete multiple evaluation runs by their IDs",
        tags={"evals"},
    )  # type: ignore
    async def delete_eval_runs(eval_run_ids: List[str], db_id: Optional[str] = None) -> dict:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_eval_runs(eval_run_ids=eval_run_ids)
        else:
            db.delete_eval_runs(eval_run_ids=eval_run_ids)

        return {"message": f"Deleted {len(eval_run_ids)} eval runs"}

    @mcp.tool(
        name="update_eval_run",
        description="Update the name of an evaluation run",
        tags={"evals"},
    )  # type: ignore
    async def update_eval_run(eval_run_id: str, name: str, db_id: Optional[str] = None) -> dict:
        db = await get_db(os.dbs, db_id)

        if isinstance(db, RemoteDb):
            result = await db.update_eval_run(eval_run_id=eval_run_id, name=name)
            return result.model_dump()

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            eval_run = await db.rename_eval_run(eval_run_id=eval_run_id, name=name, deserialize=False)
        else:
            eval_run = db.rename_eval_run(eval_run_id=eval_run_id, name=name, deserialize=False)

        if not eval_run:
            raise Exception(f"Eval run {eval_run_id} not found")

        return EvalSchema.from_dict(eval_run).model_dump()  # type: ignore

    @mcp.tool(
        name="run_eval",
        description="Run evaluation tests on agents or teams. Supports accuracy, agent_as_judge, performance, and reliability evaluations.",
        tags={"evals"},
    )  # type: ignore
    async def run_eval(
        eval_type: str,
        input_text: str,
        db_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        expected_output: Optional[str] = None,
        expected_tool_calls: Optional[List[str]] = None,
        expected_tool_call_parameters: Optional[Dict[str, Any]] = None,
        judge_criteria: Optional[str] = None,
        judge_steps: Optional[List[str]] = None,
    ) -> dict:
        from agno.agent.agent import Agent
        from agno.agent.remote import RemoteAgent
        from agno.models.utils import get_model
        from agno.os.routers.evals.schemas import EvalRunInput
        from agno.os.routers.evals.utils import (
            run_accuracy_eval,
            run_agent_as_judge_eval,
            run_performance_eval,
            run_reliability_eval,
        )
        from agno.team.remote import RemoteTeam
        from agno.team.team import Team

        db = await get_db(os.dbs, db_id)

        if agent_id and team_id:
            raise Exception("Only one of agent_id or team_id must be provided")

        if not agent_id and not team_id:
            raise Exception("One of agent_id or team_id must be provided")

        # Convert eval_type string to EvalType enum
        try:
            et = EvalType(eval_type)
        except ValueError:
            valid_types = ", ".join([t.value for t in EvalType])
            raise Exception(f"Invalid eval_type: {eval_type}. Valid types: {valid_types}")

        # Build eval input
        eval_input: Dict[str, Any] = {}
        if expected_output:
            eval_input["expected_output"] = expected_output
        if expected_tool_calls:
            eval_input["expected_tool_calls"] = expected_tool_calls
        if expected_tool_call_parameters:
            eval_input["expected_tool_call_parameters"] = expected_tool_call_parameters
        if judge_criteria:
            eval_input["judge_criteria"] = judge_criteria
        if judge_steps:
            eval_input["judge_steps"] = judge_steps

        eval_run_input = EvalRunInput(
            eval_type=et,
            input=input_text,
            agent_id=agent_id,
            team_id=team_id,
            model_id=model_id,
            model_provider=model_provider,
            eval_input=eval_input if eval_input else None,
        )

        if isinstance(db, RemoteDb):
            remote_result = await db.create_eval_run(
                eval_type=et,
                input=input_text,
                agent_id=agent_id,
                team_id=team_id,
                model_id=model_id,
                model_provider=model_provider,
                eval_input=eval_input if eval_input else None,
            )
            if remote_result:
                return remote_result.model_dump()
            else:
                raise Exception("Eval run returned no result")

        agent = None
        team = None
        default_model = None

        if agent_id:
            agent_or_remote = get_agent_by_id(agent_id=agent_id, agents=os.agents)
            if not agent_or_remote:
                raise Exception(f"Agent with id '{agent_id}' not found")

            # RemoteAgent cannot be used for local evals
            if isinstance(agent_or_remote, RemoteAgent):
                raise Exception(
                    "Cannot run evals on RemoteAgent. Use a local agent or run evals via the remote server."
                )

            agent = cast(Agent, agent_or_remote)

            if agent.model is not None and model_id is not None and model_provider is not None:
                default_model = deepcopy(agent.model)
                if model_id != agent.model.id or model_provider != agent.model.provider:
                    model_string = f"{model_provider.lower()}:{model_id.lower()}"
                    model = get_model(model_string)
                    agent.model = model

        elif team_id:
            team_or_remote = get_team_by_id(team_id=team_id, teams=os.teams)
            if not team_or_remote:
                raise Exception(f"Team with id '{team_id}' not found")

            if isinstance(team_or_remote, RemoteTeam):
                raise Exception("Cannot run evals on RemoteTeam. Use a local team or run evals via the remote server.")

            team = cast(Team, team_or_remote)

            if team.model is not None and model_id is not None and model_provider is not None:
                default_model = deepcopy(team.model)
                if model_id != team.model.id or model_provider != team.model.provider:
                    model_string = f"{model_provider.lower()}:{model_id.lower()}"
                    model = get_model(model_string)
                    team.model = model

        # Run the evaluation (db is local at this point)
        result: Optional[EvalSchema] = None
        if et == EvalType.ACCURACY:
            result = await run_accuracy_eval(
                eval_run_input=eval_run_input,
                db=db,
                agent=agent,
                team=team,
                default_model=default_model,  # type: ignore
            )
        elif et == EvalType.AGENT_AS_JUDGE:
            result = await run_agent_as_judge_eval(
                eval_run_input=eval_run_input,
                db=db,
                agent=agent,
                team=team,
                default_model=default_model,  # type: ignore
            )
        elif et == EvalType.PERFORMANCE:
            result = await run_performance_eval(
                eval_run_input=eval_run_input,
                db=db,
                agent=agent,
                team=team,
                default_model=default_model,  # type: ignore
            )
        else:
            result = await run_reliability_eval(
                eval_run_input=eval_run_input,
                db=db,
                agent=agent,
                team=team,
                default_model=default_model,  # type: ignore
            )

        if result:
            return result.model_dump()
        else:
            raise Exception("Eval run returned no result")
