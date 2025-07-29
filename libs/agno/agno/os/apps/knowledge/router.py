import json
import math
from typing import Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Path, Query, UploadFile

from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import Knowledge
from agno.os.apps.knowledge.schemas import ConfigResponseSchema, ContentResponseSchema, ReaderSchema
from agno.os.apps.utils import PaginatedResponse, PaginationInfo, SortOrder
from agno.utils.log import log_debug, log_info


def attach_routes(router: APIRouter, knowledge: Knowledge) -> APIRouter:
    @router.post("/content")
    async def upload_content(
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        url: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON metadata"),
        file: Optional[UploadFile] = File(None),
        text_content: Optional[str] = Form(None),
        reader_id: Optional[str] = Form(None),
    ):
        content_id = str(uuid4())
        log_info(f"Adding content: {name}, {description}, {url}, {metadata} with ID: {content_id}")

        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None
        if file:
            content_bytes = await file.read()
        elif text_content:
            content_bytes = text_content.encode("utf-8")
        else:
            content_bytes = None

        parsed_urls = None
        if url and url.strip():
            try:
                parsed_urls = json.loads(url)
                log_debug(f"Parsed URLs: {parsed_urls}")
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a single URL string
                parsed_urls = url

        # # Parse metadata with proper error handling
        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata}

        if text_content:
            file_data = FileData(
                content=content_bytes,
                type="manual",
            )
        elif file:
            file_data = (
                FileData(
                    content=content_bytes,
                    type=file.content_type if file.content_type else None,
                )
                if file
                else None
            )
        else:
            file_data = None

        if not name:
            if file and file.filename:
                name = file.filename
            elif url:
                name = parsed_urls

        content = Content(
            name=name,
            description=description,
            url=parsed_urls,
            metadata=parsed_metadata,
            file_data=file_data,
            size=file.size if file else None if text_content else None,
        )

        background_tasks.add_task(process_content, knowledge, content_id, content, reader_id)

        return {"content_id": content_id, "status": "processing"}

    # TODO: add and use a ContentUpdatePayload schema. Validate input fields there
    @router.patch("/content/{content_id}", response_model=ContentResponseSchema, status_code=200)
    async def update_content(
        content_id: str = Path(..., description="Content ID"),
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON metadata"),
        reader_id: Optional[str] = Form(None),
    ) -> Optional[ContentResponseSchema]:
        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None

        content = Content(
            id=content_id,
            name=name,
            description=description,
            metadata=parsed_metadata,
        )

        if reader_id:
            if reader_id in knowledge.readers:
                content.reader = knowledge.readers[reader_id]
            else:
                raise HTTPException(status_code=400, detail=f"Invalid reader_id: {reader_id}")

        content = knowledge.patch_content(content)
        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {content_id}")

        return ContentResponseSchema.from_dict(content)

    @router.get("/content", response_model=PaginatedResponse[ContentResponseSchema], status_code=200)
    def get_content(
        limit: Optional[int] = Query(default=20, description="Number of content entries to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[ContentResponseSchema]:
        contents, count = knowledge.get_content(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

        return PaginatedResponse(
            data=[
                ContentResponseSchema(
                    id=content.id,
                    name=content.name,
                    description=content.description,
                    type=content.file_type,
                    size=str(content.size) if content.size else "0",
                    metadata=content.metadata,
                    linked_to=knowledge.name,
                    status=content.status,
                    status_message=content.status_message,
                    created_at=str(content.created_at) if content.created_at else None,
                    updated_at=str(content.updated_at) if content.updated_at else None,
                )
                for content in contents
            ],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=count,
                total_pages=math.ceil(count / limit) if limit is not None and limit > 0 else 0,
            ),
        )

    @router.get("/content/{content_id}", response_model=ContentResponseSchema, status_code=200)
    def get_content_by_id(content_id: str) -> ContentResponseSchema:
        log_info(f"Getting content by id: {content_id}")

        content = knowledge.get_content_by_id(content_id=content_id)
        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {content_id}")
        response = ContentResponseSchema(
            id=content_id,
            name=content.name,
            description=content.description,
            type=content.file_type,
            size=str(len(content.file_data.content)) if content.file_data else "0",
            linked_to=knowledge.name,
            metadata=content.metadata,
            access_count=0,
            status=content.status,
            status_message=content.status_message,
            created_at=str(content.created_at) if content.created_at else None,
            updated_at=str(content.updated_at) if content.updated_at else None,
        )

        return response

    @router.delete(
        "/content/{content_id}",
        response_model=ContentResponseSchema,
        status_code=200,
        response_model_exclude_none=True,
    )
    def delete_content_by_id(content_id: str) -> ContentResponseSchema:
        knowledge.remove_content_by_id(content_id=content_id)
        log_info(f"Deleting content by id: {content_id}")

        return ContentResponseSchema(
            id=content_id,
        )

    @router.delete("/content", status_code=200)
    def delete_all_content():
        log_info("Deleting all content")
        knowledge.remove_all_content()
        return "success"

    @router.get("/content/{content_id}/status", status_code=200)
    def get_content_status(content_id: str) -> Dict[str, str]:
        log_info(f"Getting content status: {content_id}")
        result = knowledge.get_content_status(content_id=content_id)

        if isinstance(result, tuple) and len(result) == 2:
            status, status_message = result
            return {"status": status, "status_message": status_message}
        elif isinstance(result, str):
            return {"status": result, "status_message": ""}
        else:
            return {"status": "Unknown", "status_message": "Status not available"}

    @router.get("/config", status_code=200)
    def get_config() -> ConfigResponseSchema:
        readers = knowledge.get_readers()
        return ConfigResponseSchema(
            readers=[ReaderSchema(id=k, name=v.name, description=v.description) for k, v in readers.items()],
            filters=knowledge.get_filters(),
        )

    return router


def process_content(knowledge: Knowledge, content_id: str, content: Content, reader_id: Optional[str] = None):
    """Background task to process the content"""
    log_info(f"Processing content {content_id}")
    try:
        content.id = content_id
        if reader_id:
            content.reader = knowledge.readers[reader_id]
        knowledge.process_content(content)
        log_info(f"Content {content_id} processed successfully")
    except Exception as e:
        log_info(f"Error processing content {content_id}: {e}")
