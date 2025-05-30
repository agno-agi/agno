from io import BytesIO
from typing import Generator, List, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent, RunResponse
from agno.app.playground.utils import process_audio, process_document, process_image, process_video
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.run.response import RunEvent
from agno.run.team import TeamRunResponse
from agno.team.team import Team
from agno.utils.log import logger


def agent_chat_response_streamer(
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


def get_sync_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()

    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    @router.get("/status")
    def status():
        return {"status": "available"}

    def agent_process_file(
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
    def run_agent_or_team(
        message: str = Form(...),
        stream: bool = Form(True),
        monitor: bool = Form(False),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        if session_id is not None and session_id != "":
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        if agent:
            if monitor:
                agent.monitoring = True
            else:
                agent.monitoring = False
        elif team:
            if monitor:
                team.monitoring = True
            else:
                team.monitoring = False

        if files:
            if agent:
                base64_images, base64_audios, base64_videos = agent_process_file(files, agent)
            elif team:
                base64_images, base64_audios, base64_videos, document_files = team_process_file(files)

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
        else:
            if agent:
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
            elif team:
                team_run_response = team.run(
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

    return router
