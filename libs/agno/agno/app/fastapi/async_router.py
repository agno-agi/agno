import json
from dataclasses import asdict
from io import BytesIO
from typing import AsyncGenerator, List, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent, RunResponse
from agno.app.playground.utils import process_audio, process_document, process_image, process_video
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.run.response import RunResponseErrorEvent
from agno.run.team import RunResponseErrorEvent as TeamRunResponseErrorEvent
from agno.run.team import TeamRunResponseEvent
from agno.team.team import Team
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


async def agent_chat_response_streamer(
    agent: Agent,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
) -> AsyncGenerator:
    try:
        run_response = await agent.arun(
            message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            stream=True,
            stream_intermediate_steps=True,
        )
        async for run_response_chunk in run_response:
            run_response_chunk = cast(RunResponse, run_response_chunk)
            yield run_response_chunk.to_json()
    except Exception as e:
        error_response = RunResponseErrorEvent(
            content=str(e),
        )
        yield error_response.to_json()
        return


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
            run_response_chunk = cast(TeamRunResponseEvent, run_response_chunk)
            yield run_response_chunk.to_json()
    except Exception as e:
        error_response = TeamRunResponseErrorEvent(
            content=str(e),
        )
        yield error_response.to_json()
        return


def get_async_router(
    agents: Optional[List[Agent]] = None, teams: Optional[List[Team]] = None, workflows: Optional[List[Workflow]] = None
) -> APIRouter:
    router = APIRouter()

    if agents is None and teams is None and workflows is None:
        raise ValueError("Either agents, teams or workflows must be provided.")

    @router.get("/status")
    async def status():
        return {"status": "available"}

    async def agent_process_file(
        files: List[UploadFile],
        agent: Agent,
    ):
        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        for file in files:
            logger.info(f"Processing file: {file.content_type}")
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

                    contents = await file.read()
                    pdf_file = BytesIO(contents)
                    pdf_file.name = file.filename
                    file_content = PDFReader().read(pdf_file)
                    if agent.knowledge is not None:
                        await agent.knowledge.async_load_documents(file_content)
                elif file.content_type == "text/csv":
                    from agno.document.reader.csv_reader import CSVReader

                    contents = await file.read()
                    csv_file = BytesIO(contents)
                    csv_file.name = file.filename
                    file_content = CSVReader().read(csv_file)
                    if agent.knowledge is not None:
                        await agent.knowledge.async_load_documents(file_content)
                elif file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    from agno.document.reader.docx_reader import DocxReader

                    contents = await file.read()
                    docx_file = BytesIO(contents)
                    docx_file.name = file.filename
                    file_content = DocxReader().read(docx_file)
                    if agent.knowledge is not None:
                        await agent.knowledge.async_load_documents(file_content)
                elif file.content_type == "text/plain":
                    from agno.document.reader.text_reader import TextReader

                    contents = await file.read()
                    text_file = BytesIO(contents)
                    text_file.name = file.filename
                    file_content = TextReader().read(text_file)
                    if agent.knowledge is not None:
                        await agent.knowledge.async_load_documents(file_content)

                elif file.content_type == "application/json":
                    from agno.document.reader.json_reader import JSONReader

                    contents = await file.read()
                    json_file = BytesIO(contents)
                    json_file.name = file.filename
                    file_content = JSONReader().read(json_file)
                    if agent.knowledge is not None:
                        await agent.knowledge.async_load_documents(file_content)
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        return base64_images, base64_audios, base64_videos

    def team_process_file(
        files: List[UploadFile],
    ):
        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        document_files: List[FileMedia] = []
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

        return base64_images, base64_audios, base64_videos, document_files

    @router.post("/runs")
    async def run_agent_or_team_or_workflow(
        message: str = Form(None),
        stream: bool = Form(False),
        monitor: bool = Form(False),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
        agent_id: Optional[str] = Query(None),
        team_id: Optional[str] = Query(None),
        workflow_id: Optional[str] = Query(None),
        workflow_input: Optional[str] = Form(None),
    ):
        if session_id is not None and session_id != "":
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        agent = None
        team = None
        workflow = None

        # Only one of agent_id, team_id or workflow_id can be provided
        if agent_id and team_id or agent_id and workflow_id or team_id and workflow_id:
            raise HTTPException(status_code=400, detail="Only one of agent_id, team_id or workflow_id can be provided")

        if not agent_id and not team_id and not workflow_id:
            raise HTTPException(status_code=400, detail="One of agent_id, team_id or workflow_id must be provided")

        if agent_id and agents:
            agent = next((agent for agent in agents if agent.agent_id == agent_id), None)
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            if not message:
                raise HTTPException(status_code=400, detail="Message is required")
        if team_id and teams:
            team = next((team for team in teams if team.team_id == team_id), None)
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found")
            if not message:
                raise HTTPException(status_code=400, detail="Message is required")
        if workflow_id and workflows:
            workflow = next((workflow for workflow in workflows if workflow.workflow_id == workflow_id), None)
            if workflow is None:
                raise HTTPException(status_code=404, detail="Workflow not found")
            if not workflow_input:
                raise HTTPException(status_code=400, detail="Workflow input is required")

            # Parse workflow_input into a dict if it is a valid JSON
            try:
                parsed_workflow_input = json.loads(workflow_input)
                workflow_input = parsed_workflow_input
            except json.JSONDecodeError:
                pass

        if agent:
            agent.monitoring = bool(monitor)
        elif team:
            team.monitoring = bool(monitor)
        elif workflow:
            workflow.monitoring = bool(monitor)

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        document_files: List[FileMedia] = []
        if files:
            if agent:
                base64_images, base64_audios, base64_videos = await agent_process_file(files, agent)
            elif team:
                base64_images, base64_audios, base64_videos, document_files = await team_process_file(files)

        if stream:
            if agent:
                return StreamingResponse(
                    agent_chat_response_streamer(
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
            elif team:
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
            elif workflow:
                workflow_instance = workflow.deep_copy(update={"workflow_id": workflow_id})
                workflow_instance.user_id = user_id
                workflow_instance.session_name = None
                if isinstance(workflow_input, dict):
                    return StreamingResponse(
                        (json.dumps(asdict(result)) for result in await workflow_instance.arun(**workflow_input)),
                        media_type="text/event-stream",
                    )
                else:
                    return StreamingResponse(
                        (json.dumps(asdict(result)) for result in await workflow_instance.arun(workflow_input)),  # type: ignore
                        media_type="text/event-stream",
                    )
        else:
            if agent:
                run_response = cast(
                    RunResponse,
                    await agent.arun(
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
            elif team:
                team_run_response = await team.arun(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    stream=False,
                )
                return team_run_response.to_dict()
            elif workflow:
                workflow_instance = workflow.deep_copy(update={"workflow_id": workflow_id})
                workflow_instance.user_id = user_id
                workflow_instance.session_name = None
                if isinstance(workflow_input, dict):
                    return (await workflow_instance.arun(**workflow_input)).to_dict()
                else:
                    return (await workflow_instance.arun(workflow_input)).to_dict()  # type: ignore

    return router
