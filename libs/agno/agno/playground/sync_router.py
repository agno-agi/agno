import json
from dataclasses import asdict
from io import BytesIO
from typing import Any, Dict, Generator, List, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from agno.agent.agent import Agent, RunResponse
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.memory.agent import AgentMemory
from agno.memory.v2 import Memory
from agno.playground.operator import (
    format_tools,
    get_agent_by_id,
    get_session_title,
    get_session_title_from_team_session,
    get_session_title_from_workflow_session,
    get_team_by_id,
    get_workflow_by_id,
)
from agno.playground.schemas import (
    AgentGetResponse,
    AgentModel,
    AgentRenameRequest,
    AgentSessionsResponse,
    MemoryResponse,
    TeamGetResponse,
    TeamRenameRequest,
    TeamSessionResponse,
    WorkflowGetResponse,
    WorkflowRenameRequest,
    WorkflowRunRequest,
    WorkflowSessionResponse,
    WorkflowsGetResponse,
)
from agno.playground.utils import process_audio, process_document, process_image, process_video
from agno.run.response import RunEvent
from agno.run.team import TeamRunResponse
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.team.team import Team
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


def chat_response_streamer(
    agent: Agent,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
) -> Generator:
    try:
        run_response = agent.run(
            message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            stream=True,
            stream_intermediate_steps=True,
        )
        for run_response_chunk in run_response:
            run_response_chunk = cast(RunResponse, run_response_chunk)
            yield run_response_chunk.to_json()
    except Exception as e:
        error_response = RunResponse(
            content=str(e),
            event=RunEvent.run_error,
        )
        yield error_response.to_json()
        return


def team_chat_response_streamer(
    team: Team,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
) -> Generator:
    try:
        run_response = team.run(
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
        for run_response_chunk in run_response:
            run_response_chunk = cast(TeamRunResponse, run_response_chunk)
            yield run_response_chunk.to_json()
    except Exception as e:
        error_response = TeamRunResponse(
            content=str(e),
            event=RunEvent.run_error,
        )
        yield error_response.to_json()
        return


def get_sync_playground_router(
    agents: Optional[List[Agent]] = None, workflows: Optional[List[Workflow]] = None, teams: Optional[List[Team]] = None
) -> APIRouter:
    playground_router = APIRouter(prefix="/playground", tags=["Playground"])
    if agents is None and workflows is None and teams is None:
        raise ValueError("Either agents, teams or workflows must be provided.")

    # Generate IDs if they were not explicitly set on agents/teams/workflows
    if agents:
        for agent in agents:
            if agent.agent_id is None:
                agent.agent_id = str(uuid4())
    if teams:
        for team in teams:
            if team.team_id is None:
                team.team_id = str(uuid4())
    if workflows:
        for workflow in workflows:
            if workflow.workflow_id is None:
                workflow.workflow_id = str(uuid4())

    @playground_router.get("/status")
    def playground_status():
        return {"playground": "available"}

    @playground_router.get("/agents", response_model=List[AgentGetResponse])
    def get_agents():
        agent_list: List[AgentGetResponse] = []
        if agents is None:
            return agent_list

        for agent in agents:
            # We can make up a session_id here because we aren't really using the tools
            agent_tools = agent.get_tools(session_id=str(uuid4()))
            formatted_tools = format_tools(agent_tools)

            name = agent.model.name or agent.model.__class__.__name__ if agent.model else None
            provider = agent.model.provider or agent.model.__class__.__name__ if agent.model else None
            model_id = agent.model.id if agent.model else None

            # Create an agent_id if its not set on the agent
            if agent.agent_id is None:
                agent.set_agent_id()

            if provider and model_id:
                provider = f"{provider} {model_id}"
            elif name and model_id:
                provider = f"{name} {model_id}"
            elif model_id:
                provider = model_id
            else:
                provider = ""

            if agent.memory:
                memory_dict: Optional[Dict[str, Any]] = {}
                if isinstance(agent.memory, AgentMemory) and agent.memory.db:
                    memory_dict = {"name": agent.memory.db.__class__.__name__}
                elif isinstance(agent.memory, Memory) and agent.memory.db:
                    memory_dict = {"name": "Memory"}
                    if agent.memory.model is not None:
                        memory_dict["model"] = AgentModel(
                            name=agent.memory.model.name,
                            model=agent.memory.model.id,
                            provider=agent.memory.model.provider,
                        )
                    if agent.memory.db is not None:
                        memory_dict["db"] = agent.memory.db.__dict__()  # type: ignore

                else:
                    memory_dict = None
            else:
                memory_dict = None

            agent_list.append(
                AgentGetResponse(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    model=AgentModel(
                        name=name,
                        model=model_id,
                        provider=provider,
                    ),
                    add_context=agent.add_context,
                    tools=formatted_tools,
                    memory=memory_dict,
                    storage={"name": agent.storage.__class__.__name__} if agent.storage else None,
                    knowledge={"name": agent.knowledge.__class__.__name__} if agent.knowledge else None,
                    description=agent.description,
                    instructions=agent.instructions,
                )
            )

        return agent_list

    @playground_router.post("/agents/{agent_id}/runs")
    def create_agent_run(
        agent_id: str,
        message: str = Form(...),
        stream: bool = Form(True),
        monitor: bool = Form(False),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        logger.debug(f"AgentRunRequest: {message} {agent_id} {stream} {monitor} {session_id} {user_id} {files}")
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session_id is not None and session_id != "":
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        if monitor:
            agent.monitoring = True
        else:
            agent.monitoring = False

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []

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
                else:
                    # Check for knowledge base before processing documents
                    if agent.knowledge is None:
                        raise HTTPException(status_code=404, detail="KnowledgeBase not found")

                    if file.content_type == "application/pdf":
                        from agno.document.reader.pdf_reader import PDFReader

                        contents = file.file.read()
                        pdf_file = BytesIO(contents)
                        pdf_file.name = file.filename
                        file_content = PDFReader().read(pdf_file)
                        if agent.knowledge is not None:
                            agent.knowledge.load_documents(file_content)
                    elif file.content_type == "text/csv":
                        from agno.document.reader.csv_reader import CSVReader

                        contents = file.file.read()
                        csv_file = BytesIO(contents)
                        csv_file.name = file.filename
                        file_content = CSVReader().read(csv_file)
                        if agent.knowledge is not None:
                            agent.knowledge.load_documents(file_content)
                    elif file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                        from agno.document.reader.docx_reader import DocxReader

                        contents = file.file.read()
                        docx_file = BytesIO(contents)
                        docx_file.name = file.filename
                        file_content = DocxReader().read(docx_file)
                        if agent.knowledge is not None:
                            agent.knowledge.load_documents(file_content)
                    elif file.content_type == "text/plain":
                        from agno.document.reader.text_reader import TextReader

                        contents = file.file.read()
                        text_file = BytesIO(contents)
                        text_file.name = file.filename
                        file_content = TextReader().read(text_file)
                        if agent.knowledge is not None:
                            agent.knowledge.load_documents(file_content)
                    elif file.content_type == "application/json":
                        from agno.document.reader.json_reader import JSONReader

                        contents = file.file.read()
                        json_file = BytesIO(contents)
                        json_file.name = file.filename
                        file_content = JSONReader().read(json_file)
                        if agent.knowledge is not None:
                            agent.knowledge.load_documents(file_content)
                    else:
                        raise HTTPException(status_code=400, detail="Unsupported file type")

        if stream:
            return StreamingResponse(
                chat_response_streamer(
                    agent,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                ),
                media_type="text/event-stream",
            )
        else:
            run_response = cast(
                RunResponse,
                agent.run(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    stream=False,
                ),
            )
            return run_response.to_dict()

    @playground_router.get("/agents/{agent_id}/sessions")
    def get_agent_sessions(agent_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        logger.debug(f"AgentSessionsRequest: {agent_id} {user_id}")
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        agent_sessions: List[AgentSessionsResponse] = []
        all_agent_sessions: List[AgentSession] = agent.storage.get_all_sessions(user_id=user_id)  # type: ignore
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

    @playground_router.get("/agents/{agent_id}/sessions/{session_id}")
    def get_agent_session(agent_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        logger.debug(f"AgentSessionsRequest: {agent_id} {user_id} {session_id}")
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        agent_session: Optional[AgentSession] = agent.storage.read(session_id)  # type: ignore
        if agent_session is None:
            return JSONResponse(status_code=404, content="Session not found.")

        agent_session_dict = agent_session.to_dict()
        if agent_session.memory is not None:
            runs = agent_session.memory.get("runs")
            if runs is not None:
                first_run = runs[0]
                if "content" in first_run:
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

    @playground_router.post("/agents/{agent_id}/sessions/{session_id}/rename")
    def rename_agent_session(agent_id: str, session_id: str, body: AgentRenameRequest):
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content=f"couldn't find agent with {agent_id}")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        all_agent_sessions: List[AgentSession] = agent.storage.get_all_sessions(user_id=body.user_id)  # type: ignore
        for session in all_agent_sessions:
            if session.session_id == session_id:
                agent.rename_session(body.name, session_id=session_id)
                return JSONResponse(content={"message": f"successfully renamed agent {agent.name}"})

        return JSONResponse(status_code=404, content="Session not found.")

    @playground_router.delete("/agents/{agent_id}/sessions/{session_id}")
    def delete_agent_session(agent_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
        agent = get_agent_by_id(agent_id, agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        if agent.storage is None:
            return JSONResponse(status_code=404, content="Agent does not have storage enabled.")

        all_agent_sessions: List[AgentSession] = agent.storage.get_all_sessions(user_id=user_id)  # type: ignore
        for session in all_agent_sessions:
            if session.session_id == session_id:
                agent.delete_session(session_id)
                return JSONResponse(content={"message": f"successfully deleted agent {agent.name}"})

        return JSONResponse(status_code=404, content="Session not found.")

    @playground_router.get("/agents/{agent_id}/memories")
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

    @playground_router.get("/workflows", response_model=List[WorkflowsGetResponse])
    def get_workflows():
        if workflows is None:
            return []

        return [
            WorkflowsGetResponse(
                workflow_id=str(workflow.workflow_id),
                name=workflow.name,
                description=workflow.description,
            )
            for workflow in workflows
        ]

    @playground_router.get("/workflows/{workflow_id}", response_model=WorkflowGetResponse)
    def get_workflow(workflow_id: str):
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return WorkflowGetResponse(
            workflow_id=workflow.workflow_id,
            name=workflow.name,
            description=workflow.description,
            parameters=workflow._run_parameters or {},
            storage=workflow.storage.__class__.__name__ if workflow.storage else None,
        )

    @playground_router.post("/workflows/{workflow_id}/runs")
    def create_workflow_run(workflow_id: str, body: WorkflowRunRequest):
        # Retrieve the workflow by ID
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # Create a new instance of this workflow
        new_workflow_instance = workflow.deep_copy(update={"workflow_id": workflow_id})
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

    @playground_router.get("/workflows/{workflow_id}/sessions", response_model=List[WorkflowSessionResponse])
    def get_all_workflow_sessions(workflow_id: str, user_id: Optional[str] = Query(None, min_length=1)):
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
        return [
            WorkflowSessionResponse(
                title=get_session_title_from_workflow_session(session),
                session_id=session.session_id,
                session_name=session.session_data.get("session_name") if session.session_data else None,
                created_at=session.created_at,
            )
            for session in all_workflow_sessions
        ]

    @playground_router.get("/workflows/{workflow_id}/sessions/{session_id}", response_model=WorkflowSession)
    def get_workflow_session(workflow_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
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

    @playground_router.post("/workflows/{workflow_id}/sessions/{session_id}/rename")
    def rename_workflow_session(
        workflow_id: str,
        session_id: str,
        body: WorkflowRenameRequest,
    ):
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow.session_id = session_id
        workflow.rename_session(body.name)
        return JSONResponse(content={"message": f"successfully renamed workflow {workflow.name}"})

    @playground_router.delete("/workflows/{workflow_id}/sessions/{session_id}")
    def delete_workflow_session(workflow_id: str, session_id: str):
        workflow = get_workflow_by_id(workflow_id, workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow.delete_session(session_id)
        return JSONResponse(content={"message": f"successfully deleted workflow {workflow.name}"})

    @playground_router.get("/teams")
    def get_teams():
        if teams is None:
            return []

        return [TeamGetResponse.from_team(team) for team in teams]

    @playground_router.get("/teams/{team_id}")
    def get_team(team_id: str):
        team = get_team_by_id(team_id, teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        return TeamGetResponse.from_team(team)

    @playground_router.post("/teams/{team_id}/runs")
    def create_team_run(
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

        if stream:
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
            run_response = team.run(
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

    @playground_router.get("/teams/{team_id}/sessions", response_model=List[TeamSessionResponse])
    def get_all_team_sessions(team_id: str, user_id: Optional[str] = Query(None, min_length=1)):
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

    @playground_router.get("/teams/{team_id}/sessions/{session_id}")
    def get_team_session(team_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
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
                if "content" in first_run:
                    team_session_dict["runs"] = []
                    for run in runs:
                        first_user_message = None
                        for msg in run.get("messages", []):
                            if msg.get("role") == "user" and msg.get("from_history", False) is False:
                                first_user_message = msg
                                break
                        # Remove the memory from the response
                        run.pop("memory", None)
                        team_session_dict["runs"].append(
                            {
                                "message": first_user_message,
                                "response": run,
                            }
                        )
        return team_session_dict

    @playground_router.post("/teams/{team_id}/sessions/{session_id}/rename")
    def rename_team_session(team_id: str, session_id: str, body: TeamRenameRequest):
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

    @playground_router.delete("/teams/{team_id}/sessions/{session_id}")
    def delete_team_session(team_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):
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

    @playground_router.get("/team/{team_id}/memories")
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

    return playground_router
