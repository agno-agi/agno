import json
from dataclasses import asdict
from io import BytesIO
from typing import Any, AsyncGenerator, Dict, List, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from agno.agent.agent import Agent, RunResponse
from agno.os.utils import get_agent_by_id, process_audio, process_image, process_video

from agno.os.operator import (
    get_session_title,
    get_session_title_from_team_session,
    get_session_title_from_workflow_session,
    get_team_by_id,
    get_workflow_by_id,
)
from agno.os.interfaces.playground.schemas import (

    AgentRenameRequest,
    AgentSessionsResponse,
    MemoryResponse,
    TeamRenameRequest,
    TeamSessionResponse,
    WorkflowRenameRequest,
    WorkflowRunRequest,
    WorkflowSessionResponse,
    WorkflowsGetResponse,
)
from agno.os.utils import process_audio, process_document, process_image, process_video
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.memory import Memory
from agno.run.response import RunResponseErrorEvent
from agno.run.team import RunResponseErrorEvent as TeamRunResponseErrorEvent
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.team.team import Team
from agno.utils.log import logger
from agno.workflow.workflow import Workflow



async def team_chat_response_streamer(
    team: Team,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
) -> AsyncGenerator:
    try:
        run_response = await team.arun(
            message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=True,
        )
        async for run_response_chunk in run_response:
            yield run_response_chunk.to_json()
    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = TeamRunResponseErrorEvent(
            content=str(e),
        )
        yield error_response.to_json()
        return


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Agent]] = None,
    workflows: Optional[List[Workflow]] = None,
    teams: Optional[List[Team]] = None,
) -> APIRouter:
    if agents is None and workflows is None and teams is None:
        raise ValueError("Either agents, teams or workflows must be provided.")

    @router.get("/agents/{agent_id}/sessions")
    async def get_all_agent_sessions(agent_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        logger.debug(f"AgentSessionsRequest: {agent_id} {user_id}")
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        agent_sessions: List[AgentSessionsResponse] = []
        all_agent_sessions: List[AgentSession] = agent.storage.get_all_sessions(user_id=user_id, entity_id=agent_id)  # type: ignore
        for session in all_agent_sessions:
            title = get_session_title(session)
            agent_sessions.append(
                AgentSessionsResponse(
                    title=title,
                    session_id=session.session_id,
                    session_name=session.session_data.get("session_name") if session.session_data else None,
                    created_at=session.created_at,
                )
            )
        return agent_sessions

    @router.get("/agents/{agent_id}/sessions/{session_id}")
    async def get_agent_session(agent_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        logger.debug(f"AgentSessionsRequest: {agent_id} {user_id} {session_id}")
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        agent_session: Optional[AgentSession] = agent.storage.read(session_id, user_id)  # type: ignore
        if agent_session is None:
            return JSONResponse(status_code=404, content="Session not found.")

        agent_session_dict = agent_session.to_dict()
        if agent_session.memory is not None:
            runs = agent_session.memory.get("runs")
            if runs is not None:
                first_run = runs[0]
                # This is how we know it is a RunResponse or RunPaused
                if "content" in first_run or first_run.get("is_paused", False) or first_run.get("event") == "RunPaused":
                    agent_session_dict["runs"] = []

                    for run in runs:
                        first_user_message = None
                        for msg in run.get("messages", []):
                            if msg.get("role") == "user" and msg.get("from_history", False) is False:
                                first_user_message = msg
                                break
                        # Remove the memory from the response
                        run.pop("memory", None)
                        agent_session_dict["runs"].append(
                            {
                                "message": first_user_message,
                                "response": run,
                            }
                        )
        return agent_session_dict

    @router.post("/agents/{agent_id}/sessions/{session_id}/rename")
    async def rename_agent_session(agent_id: str, session_id: str, body: AgentRenameRequest):
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content=f"couldn't find agent with {agent_id}")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        all_agent_sessions: List[AgentSession] = agent.storage.get_all_sessions(user_id=body.user_id)  # type: ignore
        for session in all_agent_sessions:
            if session.session_id == session_id:
                agent.rename_session(body.name, session_id=session_id)
                return JSONResponse(content={"message": f"successfully renamed session {session.session_id}"})

        return JSONResponse(status_code=404, content="Session not found.")

    @router.delete("/agents/{agent_id}/sessions/{session_id}")
    async def delete_agent_session(agent_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        all_agent_sessions: List[AgentSession] = agent.storage.get_all_sessions(user_id=user_id, entity_id=agent_id)  # type: ignore
        for session in all_agent_sessions:
            if session.session_id == session_id:
                agent.delete_session(session_id)
                return JSONResponse(content={"message": f"successfully deleted session {session_id}"})

        return JSONResponse(status_code=404, content="Session not found.")

    @router.get("/agents/{agent_id}/memories")
    async def get_agent_memories(agent_id: str, user_id: str = Query(..., min_length=1)):
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        if agent.memory is None:
            return JSONResponse(status_code=404, content="Agent does not have memory enabled.")

        if isinstance(agent.memory, Memory):
            memories = agent.memory.get_user_memories(user_id=user_id)
            return [
                MemoryResponse(memory=memory.memory, topics=memory.topics, last_updated=memory.last_updated)
                for memory in memories
            ]
        else:
            return []

    @router.get("/workflows/{workflow_id}", response_model=WorkflowsGetResponse)
    async def get_workflow(workflow_id: str):
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return WorkflowsGetResponse(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow.description,
            parameters=workflow._run_parameters or {},
            storage=workflow.storage.__class__.__name__ if workflow.storage else None,
        )

    @router.post("/workflows/{workflow_id}/runs")
    async def create_workflow_run(workflow_id: str, body: WorkflowRunRequest):
        # Retrieve the workflow by ID
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if body.session_id is not None:
            logger.debug(f"Continuing session: {body.session_id}")
        else:
            logger.debug("Creating new session")

        # Create a new instance of this workflow
        new_workflow_instance = workflow.deep_copy(update={"workflow_id": workflow_id, "session_id": body.session_id})
        new_workflow_instance.user_id = body.user_id
        new_workflow_instance.session_name = None

        # Return based on the response type
        try:
            if new_workflow_instance._run_return_type == "RunResponse":
                # Return as a normal response
                return new_workflow_instance.run(**body.input)
            else:
                # Return as a streaming response
                return StreamingResponse(
                    (json.dumps(asdict(result)) for result in new_workflow_instance.run(**body.input)),
                    media_type="text/event-stream",
                )
        except Exception as e:
            # Handle unexpected runtime errors
            raise HTTPException(status_code=500, detail=f"Error running workflow: {str(e)}")

    @router.get("/workflows/{workflow_id}/sessions")
    async def get_all_workflow_sessions(workflow_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        # Retrieve the workflow by ID
        workflow = get_workflow_by_id(workflow_id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Ensure storage is enabled for the workflow
        if not workflow.storage:
            raise HTTPException(status_code=404, detail="Workflow does not have storage enabled")

        # Retrieve all sessions for the given workflow and user
        try:
            all_workflow_sessions: List[WorkflowSession] = workflow.storage.get_all_sessions(
                user_id=user_id, entity_id=workflow_id
            )  # type: ignore
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving sessions: {str(e)}")

        # Return the sessions
        workflow_sessions: List[WorkflowSessionResponse] = []
        for session in all_workflow_sessions:
            title = get_session_title_from_workflow_session(session)
            workflow_sessions.append(
                {
                    "title": title,
                    "session_id": session.session_id,
                    "session_name": session.session_data.get("session_name") if session.session_data else None,
                    "created_at": session.created_at,
                }  # type: ignore
            )
        return workflow_sessions

    @router.get("/workflows/{workflow_id}/sessions/{session_id}")
    async def get_workflow_session(
        workflow_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)
    ):
        # Retrieve the workflow by ID
        workflow = get_workflow_by_id(workflow_id, workflows)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Ensure storage is enabled for the workflow
        if not workflow.storage:
            raise HTTPException(status_code=404, detail="Workflow does not have storage enabled")

        # Retrieve the specific session
        try:
            workflow_session: Optional[WorkflowSession] = workflow.storage.read(session_id, user_id)  # type: ignore
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving session: {str(e)}")

        if not workflow_session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Return the session
        return workflow_session

    @router.post("/workflows/{workflow_id}/sessions/{session_id}/rename")
    async def rename_workflow_session(workflow_id: str, session_id: str, body: WorkflowRenameRequest):
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        workflow.session_id = session_id
        workflow.rename_session(body.name)
        return JSONResponse(content={"message": f"successfully renamed workflow {workflow.name}"})

    @router.delete("/workflows/{workflow_id}/sessions/{session_id}")
    async def delete_workflow_session(workflow_id: str, session_id: str):
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow.delete_session(session_id)
        return JSONResponse(content={"message": f"successfully deleted workflow {workflow.name}"})

    @router.get("/teams/{team_id}")
    async def get_team(team_id: str):
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        return TeamGetResponse.from_team(team, async_mode=True)

    @router.post("/teams/{team_id}/runs")
    async def create_team_run(
        team_id: str,
        message: str = Form(...),
        stream: bool = Form(True),
        monitor: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        logger.debug(f"Creating team run: {message} {session_id} {monitor} {user_id} {team_id} {files}")
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if session_id is not None and session_id != "":
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        if monitor:
            team.monitoring = True
        else:
            team.monitoring = False

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        document_files: List[FileMedia] = []

        if files:
            for file in files:
                if file.content_type in ["image/png", "image/jpeg", "image/jpg", "image/webp"]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        logger.error(f"Error processing image {file.filename}: {e}")
                        continue
                elif file.content_type in ["audio/wav", "audio/mp3", "audio/mpeg"]:
                    try:
                        base64_audio = process_audio(file)
                        base64_audios.append(base64_audio)
                    except Exception as e:
                        logger.error(f"Error processing audio {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "video/x-flv",
                    "video/quicktime",
                    "video/mpeg",
                    "video/mpegs",
                    "video/mpgs",
                    "video/mpg",
                    "video/mpg",
                    "video/mp4",
                    "video/webm",
                    "video/wmv",
                    "video/3gpp",
                ]:
                    try:
                        base64_video = process_video(file)
                        base64_videos.append(base64_video)
                    except Exception as e:
                        logger.error(f"Error processing video {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "application/pdf",
                    "text/csv",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/plain",
                    "application/json",
                ]:
                    document_file = process_document(file)
                    if document_file is not None:
                        document_files.append(document_file)
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        if stream and team.is_streamable:
            return StreamingResponse(
                team_chat_response_streamer(
                    team,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                ),
                media_type="text/event-stream",
            )
        else:
            run_response = await team.arun(
                message=message,
                session_id=session_id,
                user_id=user_id,
                images=base64_images if base64_images else None,
                audio=base64_audios if base64_audios else None,
                videos=base64_videos if base64_videos else None,
                files=document_files if document_files else None,
                stream=False,
            )
            return run_response.to_dict()

    @router.get("/teams/{team_id}/sessions", response_model=List[TeamSessionResponse])
    async def get_all_team_sessions(team_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if team.storage is None:
            raise HTTPException(status_code=404, detail="Team does not have storage enabled")

        try:
            all_team_sessions: List[TeamSession] = team.storage.get_all_sessions(user_id=user_id, entity_id=team_id)  # type: ignore
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving sessions: {str(e)}")

        team_sessions: List[TeamSessionResponse] = []
        for session in all_team_sessions:
            title = get_session_title_from_team_session(session)
            team_sessions.append(
                TeamSessionResponse(
                    title=title,
                    session_id=session.session_id,
                    session_name=session.session_data.get("session_name") if session.session_data else None,
                    created_at=session.created_at,
                )
            )
        return team_sessions

    @router.get("/teams/{team_id}/sessions/{session_id}")
    async def get_team_session(team_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if team.storage is None:
            raise HTTPException(status_code=404, detail="Team does not have storage enabled")

        try:
            team_session: Optional[TeamSession] = team.storage.read(session_id, user_id)  # type: ignore
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving session: {str(e)}")

        if not team_session:
            raise HTTPException(status_code=404, detail="Session not found")

        team_session_dict = team_session.to_dict()
        if team_session.memory is not None:
            runs = team_session.memory.get("runs")
            if runs is not None:
                first_run = runs[0]
                # This is how we know it is a RunResponse or RunPaused
                if "content" in first_run or first_run.get("is_paused", False) or first_run.get("event") == "RunPaused":
                    team_session_dict["runs"] = []
                    for run in runs:
                        # We skip runs that are not from the parent team
                        if run.get("team_session_id") is not None and run.get("team_session_id") == session_id:
                            continue

                        first_user_message = None
                        for msg in run.get("messages", []):
                            if msg.get("role") == "user" and msg.get("from_history", False) is False:
                                first_user_message = msg
                                break
                        # Remove the memory from the response
                        team_session_dict.pop("memory", None)
                        team_session_dict["runs"].append(
                            {
                                "message": first_user_message,
                                "response": run,
                            }
                        )

        return team_session_dict

    @router.post("/teams/{team_id}/sessions/{session_id}/rename")
    async def rename_team_session(team_id: str, session_id: str, body: TeamRenameRequest):
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if team.storage is None:
            raise HTTPException(status_code=404, detail="Team does not have storage enabled")

        all_team_sessions: List[TeamSession] = team.storage.get_all_sessions(user_id=body.user_id, entity_id=team_id)  # type: ignore
        for session in all_team_sessions:
            if session.session_id == session_id:
                team.rename_session(body.name, session_id=session_id)
                return JSONResponse(content={"message": f"successfully renamed team session {body.name}"})

        raise HTTPException(status_code=404, detail="Session not found")

    @router.delete("/teams/{team_id}/sessions/{session_id}")
    async def delete_team_session(team_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if team.storage is None:
            raise HTTPException(status_code=404, detail="Team does not have storage enabled")

        all_team_sessions: List[TeamSession] = team.storage.get_all_sessions(user_id=user_id, entity_id=team_id)  # type: ignore
        for session in all_team_sessions:
            if session.session_id == session_id:
                team.delete_session(session_id)
                return JSONResponse(content={"message": f"successfully deleted team session {session_id}"})

        raise HTTPException(status_code=404, detail="Session not found")

    @router.get("/team/{team_id}/memories")
    async def get_team_memories(team_id: str, user_id: str = Query(..., min_length=1)):
        team = get_team_by_id(team_id, teams)
        if team is None:
            return JSONResponse(status_code=404, content="Teem not found.")

        if team.memory is None:
            return JSONResponse(status_code=404, content="Team does not have memory enabled.")

        if isinstance(team.memory, Memory):
            memories = team.memory.get_user_memories(user_id=user_id)
            return [
                MemoryResponse(memory=memory.memory, topics=memory.topics, last_updated=memory.last_updated)
                for memory in memories
            ]
        else:
            return []

    return router
