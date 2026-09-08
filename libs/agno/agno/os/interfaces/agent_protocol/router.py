"""Router for the Agent Protocol interface, exposing Agno Agents/Teams/Workflows
via Agent Protocol-compatible endpoints.

The endpoints are designed to be compatible with the LangGraph SDK client,
which is used by the `deepagents` package for async subagent communication.
"""

import asyncio
import copy
import json
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agent_protocol.utils import (
    agent_to_ap_info,
    extract_messages_from_input,
    now_iso,
    run_output_to_messages,
    team_to_ap_info,
    workflow_to_ap_info,
)
from agno.os.utils import get_agent_by_id, get_team_by_id, get_workflow_by_id
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow

# In-memory state stores (process-scoped)
_threads: Dict[str, Dict[str, Any]] = {}
_runs: Dict[str, Dict[str, Any]] = {}
_run_tasks: Dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
_store: Dict[str, Dict[str, Any]] = {}


def _make_thread(
    thread_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new thread dict matching LangGraph SDK schema."""
    tid = thread_id or str(uuid4())
    now = now_iso()
    return {
        "thread_id": tid,
        "created_at": now,
        "updated_at": now,
        "metadata": metadata or {},
        "status": "idle",
        "values": {},
        "interrupts": {},
    }


def _make_run(
    run_id: str,
    thread_id: str,
    assistant_id: str,
    status: str = "pending",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new run dict matching LangGraph SDK schema."""
    now = now_iso()
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "created_at": now,
        "updated_at": now,
        "status": status,
        "metadata": metadata or {},
        "multitask_strategy": "reject",
    }


def _find_runnable(
    assistant_id: str,
    agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
) -> Optional[Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow]]:
    """Find an agent, team, or workflow by assistant_id."""
    if agents:
        agent_result = get_agent_by_id(assistant_id, agents)
        if agent_result:
            return agent_result
    if teams:
        team_result = get_team_by_id(assistant_id, teams)
        if team_result:
            return team_result
    if workflows:
        workflow_result = get_workflow_by_id(assistant_id, workflows)
        if workflow_result:
            return workflow_result
    return None


def _get_default_assistant_id(
    agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
) -> Optional[str]:
    """Get the default assistant ID (first registered agent/team/workflow)."""
    if agents and len(agents) > 0:
        return agents[0].id or agents[0].name
    if teams and len(teams) > 0:
        return teams[0].id or teams[0].name
    if workflows and len(workflows) > 0:
        return workflows[0].id or workflows[0].name
    return None


async def _execute_agent_run(
    runnable: Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow],
    input_text: str,
    run_id: str,
    thread_id: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Execute an agent run and update run/thread state."""
    try:
        _runs[run_id]["status"] = "running"
        _runs[run_id]["updated_at"] = now_iso()

        if _threads.get(thread_id):
            _threads[thread_id]["status"] = "busy"
            _threads[thread_id]["updated_at"] = now_iso()

        if isinstance(runnable, (Agent, RemoteAgent)):
            agent_response = await runnable.arun(
                input=input_text,
                session_id=session_id or thread_id,
                stream=False,
            )
            # Store output in thread values
            messages = run_output_to_messages(agent_response)
            # Include the user input message too
            all_messages = [{"type": "human", "content": input_text}] + messages
        elif isinstance(runnable, (Team, RemoteTeam)):
            team_response = await runnable.arun(
                input=input_text,
                session_id=session_id or thread_id,
                stream=False,
            )
            messages = []
            if hasattr(team_response, "content") and team_response.content:
                messages.append({"type": "ai", "content": team_response.content})
            all_messages = [{"type": "human", "content": input_text}] + messages
        else:
            # Workflow
            workflow_response = await runnable.arun(
                input=input_text,
                session_id=session_id or thread_id,
            )
            messages = []
            if hasattr(workflow_response, "content") and workflow_response.content:
                messages.append({"type": "ai", "content": workflow_response.content})
            all_messages = [{"type": "human", "content": input_text}] + messages

        # Update thread values with messages
        if _threads.get(thread_id):
            existing = _threads[thread_id].get("values", {})
            existing_msgs = existing.get("messages", []) if isinstance(existing, dict) else []
            _threads[thread_id]["values"] = {"messages": existing_msgs + all_messages}
            _threads[thread_id]["status"] = "idle"
            _threads[thread_id]["updated_at"] = now_iso()

        _runs[run_id]["status"] = "success"
        _runs[run_id]["updated_at"] = now_iso()

    except asyncio.CancelledError:
        _runs[run_id]["status"] = "interrupted"
        _runs[run_id]["updated_at"] = now_iso()
        if _threads.get(thread_id):
            _threads[thread_id]["status"] = "interrupted"
            _threads[thread_id]["updated_at"] = now_iso()
    except Exception as e:
        _runs[run_id]["status"] = "error"
        _runs[run_id]["updated_at"] = now_iso()
        _runs[run_id]["error"] = str(e)
        if _threads.get(thread_id):
            _threads[thread_id]["status"] = "error"
            _threads[thread_id]["updated_at"] = now_iso()


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    workflows: Optional[List[Union[Workflow, RemoteWorkflow]]] = None,
) -> APIRouter:
    if agents is None and teams is None and workflows is None:
        raise ValueError("Agents, Teams, or Workflows are required to setup the Agent Protocol interface.")

    # =========================================================================
    # THREADS
    # =========================================================================

    @router.post(
        "/threads",
        operation_id="ap_create_thread",
        name="ap_create_thread",
    )
    async def create_thread(request: Request):
        """Create a new thread."""
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        thread_id = body.get("thread_id") if body else None
        metadata = body.get("metadata") if body else None
        thread = _make_thread(thread_id=thread_id, metadata=metadata)
        _threads[thread["thread_id"]] = thread
        return JSONResponse(content=thread)

    @router.get(
        "/threads/{thread_id}",
        operation_id="ap_get_thread",
        name="ap_get_thread",
    )
    async def get_thread(thread_id: str):
        """Get a thread by ID."""
        thread = _threads.get(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        return JSONResponse(content=thread)

    @router.patch(
        "/threads/{thread_id}",
        operation_id="ap_update_thread",
        name="ap_update_thread",
    )
    async def update_thread(request: Request, thread_id: str):
        """Update a thread's values or metadata."""
        thread = _threads.get(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        body = await request.json()
        if "metadata" in body:
            thread["metadata"].update(body["metadata"])
        if "values" in body:
            thread["values"] = body["values"]
        thread["updated_at"] = now_iso()
        return JSONResponse(content=thread)

    @router.delete(
        "/threads/{thread_id}",
        operation_id="ap_delete_thread",
        name="ap_delete_thread",
    )
    async def delete_thread(thread_id: str):
        """Delete a thread."""
        if thread_id not in _threads:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        del _threads[thread_id]
        return JSONResponse(content={"status": "ok"})

    @router.post(
        "/threads/{thread_id}/copy",
        operation_id="ap_copy_thread",
        name="ap_copy_thread",
    )
    async def copy_thread(thread_id: str):
        """Copy a thread."""
        thread = _threads.get(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        new_thread = copy.deepcopy(thread)
        new_thread["thread_id"] = str(uuid4())
        new_thread["created_at"] = now_iso()
        new_thread["updated_at"] = now_iso()
        _threads[new_thread["thread_id"]] = new_thread
        return JSONResponse(content=new_thread)

    @router.post(
        "/threads/search",
        operation_id="ap_search_threads",
        name="ap_search_threads",
    )
    async def search_threads(request: Request):
        """Search threads."""
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        status_filter = body.get("status") if body else None
        metadata_filter = body.get("metadata") if body else None
        limit = body.get("limit", 10) if body else 10
        offset = body.get("offset", 0) if body else 0

        results = list(_threads.values())
        if status_filter:
            results = [t for t in results if t.get("status") == status_filter]
        if metadata_filter:
            filtered = []
            for t in results:
                match = all(t.get("metadata", {}).get(k) == v for k, v in metadata_filter.items())
                if match:
                    filtered.append(t)
            results = filtered
        return JSONResponse(content=results[offset : offset + limit])

    @router.get(
        "/threads/{thread_id}/history",
        operation_id="ap_get_thread_history",
        name="ap_get_thread_history",
    )
    async def get_thread_history(thread_id: str):
        """Get thread history (checkpoint-based). Returns current state as single entry."""
        thread = _threads.get(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        # Return current state as a single history entry
        state = {
            "values": thread.get("values", {}),
            "next": [],
            "checkpoint": {"thread_id": thread_id, "checkpoint_id": str(uuid4())},
            "metadata": thread.get("metadata", {}),
            "created_at": thread.get("created_at"),
            "parent_checkpoint": None,
            "tasks": [],
            "interrupts": [],
        }
        return JSONResponse(content=[state])

    # =========================================================================
    # BACKGROUND RUNS (thread-scoped)
    # =========================================================================

    @router.post(
        "/threads/{thread_id}/runs",
        operation_id="ap_create_thread_run",
        name="ap_create_thread_run",
    )
    async def create_thread_run(request: Request, thread_id: str):
        """Create a background run on a thread."""
        body = await request.json()
        assistant_id = body.get("assistant_id") or _get_default_assistant_id(agents, teams, workflows)
        if not assistant_id:
            raise HTTPException(status_code=400, detail="assistant_id is required")

        runnable = _find_runnable(assistant_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

        # Ensure thread exists
        if thread_id not in _threads:
            if_not_exists = body.get("if_not_exists", "reject")
            if if_not_exists == "create":
                _threads[thread_id] = _make_thread(thread_id=thread_id)
            else:
                raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        # Handle multitask_strategy
        multitask = body.get("multitask_strategy")
        if multitask == "interrupt":
            # Cancel any existing runs on this thread
            for rid, run in list(_runs.items()):
                if run.get("thread_id") == thread_id and run.get("status") in ("pending", "running"):
                    task = _run_tasks.get(rid)
                    if task and not task.done():
                        task.cancel()
                    _runs[rid]["status"] = "interrupted"
                    _runs[rid]["updated_at"] = now_iso()

        # Extract input
        input_data = body.get("input", {})
        input_text = extract_messages_from_input(input_data) or ""

        # Create run
        run_id = str(uuid4())
        run = _make_run(run_id, thread_id, assistant_id, metadata=body.get("metadata"))
        _runs[run_id] = run

        # Execute asynchronously
        task = asyncio.create_task(
            _execute_agent_run(
                runnable=runnable,
                input_text=input_text,
                run_id=run_id,
                thread_id=thread_id,
            )
        )
        _run_tasks[run_id] = task

        return JSONResponse(content=run)

    @router.get(
        "/threads/{thread_id}/runs/{run_id}",
        operation_id="ap_get_thread_run",
        name="ap_get_thread_run",
    )
    async def get_thread_run(thread_id: str, run_id: str):
        """Get a run's status."""
        run = _runs.get(run_id)
        if not run or run.get("thread_id") != thread_id:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return JSONResponse(content=run)

    @router.post(
        "/threads/{thread_id}/runs/{run_id}/cancel",
        operation_id="ap_cancel_thread_run",
        name="ap_cancel_thread_run",
    )
    async def cancel_thread_run(thread_id: str, run_id: str):
        """Cancel a run."""
        run = _runs.get(run_id)
        if not run or run.get("thread_id") != thread_id:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        task = _run_tasks.get(run_id)
        if task and not task.done():
            task.cancel()

        run["status"] = "interrupted"
        run["updated_at"] = now_iso()

        if _threads.get(thread_id):
            _threads[thread_id]["status"] = "interrupted"
            _threads[thread_id]["updated_at"] = now_iso()

        return JSONResponse(content=run)

    @router.get(
        "/threads/{thread_id}/runs",
        operation_id="ap_list_thread_runs",
        name="ap_list_thread_runs",
    )
    async def list_thread_runs(thread_id: str):
        """List runs for a thread."""
        runs = [r for r in _runs.values() if r.get("thread_id") == thread_id]
        return JSONResponse(content=runs)

    @router.get(
        "/threads/{thread_id}/runs/{run_id}/join",
        operation_id="ap_join_thread_run",
        name="ap_join_thread_run",
    )
    async def join_thread_run(thread_id: str, run_id: str):
        """Wait for a run to complete and return its output."""
        run = _runs.get(run_id)
        if not run or run.get("thread_id") != thread_id:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        task = _run_tasks.get(run_id)
        if task and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass

        thread = _threads.get(thread_id, {})
        return JSONResponse(
            content={
                "run": _runs.get(run_id, {}),
                "values": thread.get("values", {}),
                "messages": thread.get("values", {}).get("messages", []),
            }
        )

    # =========================================================================
    # STATELESS RUNS
    # =========================================================================

    @router.post(
        "/runs/wait",
        operation_id="ap_create_run_wait",
        name="ap_create_run_wait",
    )
    async def create_run_wait(request: Request):
        """Create a stateless run and wait for the result."""
        body = await request.json()
        assistant_id = (
            body.get("agent_id") or body.get("assistant_id") or _get_default_assistant_id(agents, teams, workflows)
        )
        if not assistant_id:
            raise HTTPException(status_code=400, detail="agent_id is required")

        runnable = _find_runnable(assistant_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Agent {assistant_id} not found")

        # Extract input
        input_data = body.get("input", {})
        input_text = extract_messages_from_input(input_data) or ""

        # Also check messages field
        if not input_text:
            messages = body.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("content"):
                    input_text = str(msg["content"])
                    break

        # Create ephemeral thread and run
        thread_id = body.get("thread_id") or str(uuid4())
        run_id = str(uuid4())

        _threads[thread_id] = _make_thread(thread_id=thread_id)
        _runs[run_id] = _make_run(run_id, thread_id, assistant_id)

        # Execute synchronously (wait)
        await _execute_agent_run(
            runnable=runnable,
            input_text=input_text,
            run_id=run_id,
            thread_id=thread_id,
        )

        thread = _threads.get(thread_id, {})
        result = {
            "run": _runs.get(run_id, {}),
            "values": thread.get("values", {}),
            "messages": thread.get("values", {}).get("messages", []),
        }

        # Clean up ephemeral thread if on_completion=delete
        on_completion = body.get("on_completion", "delete" if not body.get("thread_id") else "keep")
        if on_completion == "delete":
            _threads.pop(thread_id, None)
            _runs.pop(run_id, None)

        return JSONResponse(content=result)

    @router.post(
        "/runs/stream",
        operation_id="ap_create_run_stream",
        name="ap_create_run_stream",
    )
    async def create_run_stream(request: Request):
        """Create a stateless run and stream the output."""
        body = await request.json()
        assistant_id = (
            body.get("agent_id") or body.get("assistant_id") or _get_default_assistant_id(agents, teams, workflows)
        )
        if not assistant_id:
            raise HTTPException(status_code=400, detail="agent_id is required")

        runnable = _find_runnable(assistant_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Agent {assistant_id} not found")

        input_data = body.get("input", {})
        input_text = extract_messages_from_input(input_data) or ""
        if not input_text:
            messages = body.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("content"):
                    input_text = str(msg["content"])
                    break

        thread_id = body.get("thread_id") or str(uuid4())
        run_id = str(uuid4())

        async def stream_response():
            _threads[thread_id] = _make_thread(thread_id=thread_id)
            _runs[run_id] = _make_run(run_id, thread_id, assistant_id, status="running")

            # Send metadata event
            yield f"event: metadata\ndata: {json.dumps({'run_id': run_id})}\n\n"

            try:
                if isinstance(runnable, (Agent, RemoteAgent)):
                    all_content = []
                    async for chunk in runnable.arun(  # type: ignore[union-attr]
                        input=input_text,
                        session_id=thread_id,
                        stream=True,
                        stream_events=True,
                    ):
                        if hasattr(chunk, "content") and chunk.content:
                            all_content.append(chunk.content)
                            data = {
                                "type": "messages",
                                "ns": [],
                                "data": [{"type": "ai", "content": chunk.content}],
                            }
                            yield f"event: messages\ndata: {json.dumps(data)}\n\n"

                    # Final values event
                    full_content = "".join(all_content)
                    values_data = {
                        "type": "values",
                        "ns": [],
                        "data": {
                            "messages": [
                                {"type": "human", "content": input_text},
                                {"type": "ai", "content": full_content},
                            ]
                        },
                        "interrupts": [],
                    }
                    yield f"event: values\ndata: {json.dumps(values_data)}\n\n"

                    _runs[run_id]["status"] = "success"
                else:
                    # For teams/workflows, run non-streaming and send result
                    await _execute_agent_run(
                        runnable=runnable,
                        input_text=input_text,
                        run_id=run_id,
                        thread_id=thread_id,
                    )
                    thread = _threads.get(thread_id, {})
                    values_data = {
                        "type": "values",
                        "ns": [],
                        "data": thread.get("values", {}),
                        "interrupts": [],
                    }
                    yield f"event: values\ndata: {json.dumps(values_data)}\n\n"

            except Exception as e:
                _runs[run_id]["status"] = "error"
                error_data = {"status": "error", "message": str(e)}
                yield f"event: error\ndata: {json.dumps(error_data)}\n\n"

            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # =========================================================================
    # BACKGROUND RUNS (stateless)
    # =========================================================================

    @router.post(
        "/runs",
        operation_id="ap_create_background_run",
        name="ap_create_background_run",
    )
    async def create_background_run(request: Request):
        """Create a stateless background run."""
        body = await request.json()
        assistant_id = (
            body.get("agent_id") or body.get("assistant_id") or _get_default_assistant_id(agents, teams, workflows)
        )
        if not assistant_id:
            raise HTTPException(status_code=400, detail="agent_id is required")

        runnable = _find_runnable(assistant_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Agent {assistant_id} not found")

        input_data = body.get("input", {})
        input_text = extract_messages_from_input(input_data) or ""

        thread_id = body.get("thread_id") or str(uuid4())
        run_id = str(uuid4())

        if thread_id not in _threads:
            _threads[thread_id] = _make_thread(thread_id=thread_id)

        run = _make_run(run_id, thread_id, assistant_id, metadata=body.get("metadata"))
        _runs[run_id] = run

        task = asyncio.create_task(
            _execute_agent_run(
                runnable=runnable,
                input_text=input_text,
                run_id=run_id,
                thread_id=thread_id,
            )
        )
        _run_tasks[run_id] = task

        return JSONResponse(content=run)

    @router.get(
        "/runs/{run_id}",
        operation_id="ap_get_run",
        name="ap_get_run",
    )
    async def get_run(run_id: str):
        """Get a run by ID."""
        run = _runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return JSONResponse(content=run)

    @router.get(
        "/runs/{run_id}/wait",
        operation_id="ap_wait_run",
        name="ap_wait_run",
    )
    async def wait_run(run_id: str):
        """Wait for a run to finish."""
        run = _runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        task = _run_tasks.get(run_id)
        if task and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass

        thread_id = run.get("thread_id", "")
        thread = _threads.get(thread_id, {})
        return JSONResponse(
            content={
                "run": _runs.get(run_id, {}),
                "values": thread.get("values", {}),
                "messages": thread.get("values", {}).get("messages", []),
            }
        )

    @router.post(
        "/runs/{run_id}/cancel",
        operation_id="ap_cancel_run",
        name="ap_cancel_run",
    )
    async def cancel_run(run_id: str):
        """Cancel a run."""
        run = _runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        task = _run_tasks.get(run_id)
        if task and not task.done():
            task.cancel()

        run["status"] = "interrupted"
        run["updated_at"] = now_iso()
        return JSONResponse(content=run)

    @router.delete(
        "/runs/{run_id}",
        operation_id="ap_delete_run",
        name="ap_delete_run",
    )
    async def delete_run(run_id: str):
        """Delete a finished run."""
        run = _runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        if run.get("status") in ("pending", "running"):
            raise HTTPException(status_code=409, detail="Cannot delete a running run. Cancel it first.")
        _runs.pop(run_id, None)
        _run_tasks.pop(run_id, None)
        return JSONResponse(content={"status": "ok"})

    @router.post(
        "/runs/search",
        operation_id="ap_search_runs",
        name="ap_search_runs",
    )
    async def search_runs(request: Request):
        """Search runs."""
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        status_filter = body.get("status") if body else None
        thread_id_filter = body.get("thread_id") if body else None
        limit = body.get("limit", 10) if body else 10
        offset = body.get("offset", 0) if body else 0

        results = list(_runs.values())
        if status_filter:
            results = [r for r in results if r.get("status") == status_filter]
        if thread_id_filter:
            results = [r for r in results if r.get("thread_id") == thread_id_filter]
        return JSONResponse(content=results[offset : offset + limit])

    # =========================================================================
    # AGENTS (Introspection)
    # =========================================================================

    @router.post(
        "/agents/search",
        operation_id="ap_search_agents",
        name="ap_search_agents",
    )
    async def search_agents(request: Request):
        """List all registered agents/teams/workflows."""
        result = []
        if agents:
            for agent in agents:
                result.append(agent_to_ap_info(agent))
        if teams:
            for team in teams:
                result.append(team_to_ap_info(team))
        if workflows:
            for workflow in workflows:
                result.append(workflow_to_ap_info(workflow))
        return JSONResponse(content=result)

    @router.get(
        "/agents/{agent_id}",
        operation_id="ap_get_agent",
        name="ap_get_agent",
    )
    async def get_agent(agent_id: str):
        """Get agent info by ID."""
        if agents:
            a = get_agent_by_id(agent_id, agents)
            if a:
                return JSONResponse(content=agent_to_ap_info(a))
        if teams:
            t = get_team_by_id(agent_id, teams)
            if t:
                return JSONResponse(content=team_to_ap_info(t))
        if workflows:
            w = get_workflow_by_id(agent_id, workflows)
            if w:
                return JSONResponse(content=workflow_to_ap_info(w))
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    @router.get(
        "/agents/{agent_id}/schemas",
        operation_id="ap_get_agent_schemas",
        name="ap_get_agent_schemas",
    )
    async def get_agent_schemas(agent_id: str):
        """Get agent input/output/state/config schemas."""
        # Default schemas for message-based agents
        input_schema = {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                }
            },
        }
        output_schema = {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                }
            },
        }

        # Check if agent has custom output_schema
        runnable = _find_runnable(agent_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return JSONResponse(
            content={
                "agent_id": agent_id,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "state_schema": None,
                "config_schema": None,
            }
        )

    # =========================================================================
    # STORE
    # =========================================================================

    @router.put(
        "/store/items",
        operation_id="ap_put_store_item",
        name="ap_put_store_item",
    )
    async def put_store_item(request: Request):
        """Create or update an item in the store."""
        body = await request.json()
        namespace = body.get("namespace", [])
        key = body.get("key")
        value = body.get("value", {})
        if not key:
            raise HTTPException(status_code=400, detail="key is required")
        store_key = "/".join(namespace) + "/" + key
        _store[store_key] = {
            "namespace": namespace,
            "key": key,
            "value": value,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        return JSONResponse(content={"status": "ok"})

    @router.get(
        "/store/items",
        operation_id="ap_get_store_item",
        name="ap_get_store_item",
    )
    async def get_store_item(request: Request):
        """Get an item from the store."""
        namespace = request.query_params.getlist("namespace")
        key = request.query_params.get("key")
        if not key:
            raise HTTPException(status_code=400, detail="key is required")
        store_key = "/".join(namespace) + "/" + key
        item = _store.get(store_key)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return JSONResponse(content=item)

    @router.delete(
        "/store/items",
        operation_id="ap_delete_store_item",
        name="ap_delete_store_item",
    )
    async def delete_store_item(request: Request):
        """Delete an item from the store."""
        body = await request.json()
        namespace = body.get("namespace", [])
        key = body.get("key")
        if not key:
            raise HTTPException(status_code=400, detail="key is required")
        store_key = "/".join(namespace) + "/" + key
        _store.pop(store_key, None)
        return JSONResponse(content={"status": "ok"})

    @router.post(
        "/store/items/search",
        operation_id="ap_search_store_items",
        name="ap_search_store_items",
    )
    async def search_store_items(request: Request):
        """Search items in the store."""
        body = await request.json()
        namespace_prefix = body.get("namespace_prefix", [])
        limit = body.get("limit", 10)
        offset = body.get("offset", 0)

        prefix = "/".join(namespace_prefix)
        results = []
        for store_key, item in _store.items():
            if store_key.startswith(prefix):
                results.append(item)

        return JSONResponse(content={"items": results[offset : offset + limit]})

    @router.post(
        "/store/namespaces",
        operation_id="ap_list_store_namespaces",
        name="ap_list_store_namespaces",
    )
    async def list_store_namespaces(request: Request):
        """List namespaces in the store."""
        namespaces = set()
        for item in _store.values():
            ns = tuple(item.get("namespace", []))
            namespaces.add(ns)
        return JSONResponse(content=[list(ns) for ns in namespaces])

    # =========================================================================
    # STREAMING RUNS (thread-scoped)
    # =========================================================================

    @router.post(
        "/threads/{thread_id}/runs/stream",
        operation_id="ap_stream_thread_run",
        name="ap_stream_thread_run",
    )
    async def stream_thread_run(request: Request, thread_id: str):
        """Create a run on a thread and stream the output."""
        body = await request.json()
        assistant_id = body.get("assistant_id") or _get_default_assistant_id(agents, teams, workflows)
        if not assistant_id:
            raise HTTPException(status_code=400, detail="assistant_id is required")

        runnable = _find_runnable(assistant_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

        if thread_id not in _threads:
            if_not_exists = body.get("if_not_exists", "reject")
            if if_not_exists == "create":
                _threads[thread_id] = _make_thread(thread_id=thread_id)
            else:
                raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        input_data = body.get("input", {})
        input_text = extract_messages_from_input(input_data) or ""
        run_id = str(uuid4())

        async def stream_response():
            _runs[run_id] = _make_run(run_id, thread_id, assistant_id, status="running")

            yield f"event: metadata\ndata: {json.dumps({'run_id': run_id})}\n\n"

            try:
                if isinstance(runnable, (Agent, RemoteAgent)):
                    all_content = []
                    async for chunk in runnable.arun(  # type: ignore[union-attr]
                        input=input_text,
                        session_id=thread_id,
                        stream=True,
                        stream_events=True,
                    ):
                        if hasattr(chunk, "content") and chunk.content:
                            all_content.append(chunk.content)
                            data = {
                                "type": "messages",
                                "ns": [],
                                "data": [{"type": "ai", "content": chunk.content}],
                            }
                            yield f"event: messages\ndata: {json.dumps(data)}\n\n"

                    full_content = "".join(all_content)
                    all_messages = [
                        {"type": "human", "content": input_text},
                        {"type": "ai", "content": full_content},
                    ]

                    if _threads.get(thread_id):
                        existing = _threads[thread_id].get("values", {})
                        existing_msgs = existing.get("messages", []) if isinstance(existing, dict) else []
                        _threads[thread_id]["values"] = {"messages": existing_msgs + all_messages}
                        _threads[thread_id]["status"] = "idle"
                        _threads[thread_id]["updated_at"] = now_iso()

                    values_data = {
                        "type": "values",
                        "ns": [],
                        "data": _threads.get(thread_id, {}).get("values", {}),
                        "interrupts": [],
                    }
                    yield f"event: values\ndata: {json.dumps(values_data)}\n\n"
                    _runs[run_id]["status"] = "success"
                else:
                    await _execute_agent_run(
                        runnable=runnable,
                        input_text=input_text,
                        run_id=run_id,
                        thread_id=thread_id,
                    )
                    thread = _threads.get(thread_id, {})
                    values_data = {
                        "type": "values",
                        "ns": [],
                        "data": thread.get("values", {}),
                        "interrupts": [],
                    }
                    yield f"event: values\ndata: {json.dumps(values_data)}\n\n"

            except Exception as e:
                _runs[run_id]["status"] = "error"
                error_data = {"status": "error", "message": str(e)}
                yield f"event: error\ndata: {json.dumps(error_data)}\n\n"

            _runs[run_id]["updated_at"] = now_iso()
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post(
        "/threads/{thread_id}/runs/wait",
        operation_id="ap_wait_thread_run",
        name="ap_wait_thread_run",
    )
    async def wait_thread_run(request: Request, thread_id: str):
        """Create a run on a thread and wait for it to complete."""
        body = await request.json()
        assistant_id = body.get("assistant_id") or _get_default_assistant_id(agents, teams, workflows)
        if not assistant_id:
            raise HTTPException(status_code=400, detail="assistant_id is required")

        runnable = _find_runnable(assistant_id, agents, teams, workflows)
        if not runnable:
            raise HTTPException(status_code=404, detail=f"Assistant {assistant_id} not found")

        if thread_id not in _threads:
            if_not_exists = body.get("if_not_exists", "reject")
            if if_not_exists == "create":
                _threads[thread_id] = _make_thread(thread_id=thread_id)
            else:
                raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

        input_data = body.get("input", {})
        input_text = extract_messages_from_input(input_data) or ""
        run_id = str(uuid4())

        _runs[run_id] = _make_run(run_id, thread_id, assistant_id, metadata=body.get("metadata"))

        await _execute_agent_run(
            runnable=runnable,
            input_text=input_text,
            run_id=run_id,
            thread_id=thread_id,
        )

        thread = _threads.get(thread_id, {})
        return JSONResponse(
            content={
                "run": _runs.get(run_id, {}),
                "values": thread.get("values", {}),
                "messages": thread.get("values", {}).get("messages", []),
            }
        )

    return router
