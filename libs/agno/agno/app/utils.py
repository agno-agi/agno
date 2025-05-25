from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.utils.log import logger


def process_image(file: UploadFile) -> Image:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Image(content=content)


def process_audio(file: UploadFile) -> Audio:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    format = None
    if file.filename and "." in file.filename:
        format = file.filename.split(".")[-1].lower()
    elif file.content_type:
        format = file.content_type.split("/")[-1]

    return Audio(content=content, format=format)


def process_video(file: UploadFile) -> Video:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Video(content=content, format=file.content_type)


def process_document(file: UploadFile) -> Optional[FileMedia]:
    try:
        content = file.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        return FileMedia(content=content, mime_type=file.content_type)
    except Exception as e:
        logger.error(f"Error processing document {file.filename}: {e}")
        return None


def generate_id(name: Optional[str] = None) -> str:
    if name:
        return name.lower().replace(" ", "-").replace("_", "-")
    else:
        return str(uuid4())
