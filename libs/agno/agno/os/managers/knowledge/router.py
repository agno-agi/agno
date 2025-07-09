import json
import math
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Path, Query, UploadFile

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.source import Source, SourceContent
from agno.os.managers.knowledge.schemas import ConfigResponseSchema, ReaderSchema, SourceResponseSchema
from agno.os.managers.utils import PaginatedResponse, PaginationInfo, SortOrder
from agno.utils.log import log_info


def attach_routes(router: APIRouter, knowledge: Knowledge) -> APIRouter:
    @router.post("/sources")
    async def upload_source(
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        url: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON metadata"),
        file: Optional[UploadFile] = File(None),
        reader_id: Optional[str] = Form(None),
    ):
        log_info(f"Uploading sources: {name}, {description}, {url}, {metadata}")
        # # Generate ID immediately
        source_id = str(uuid4())
        log_info(f"Source ID: {source_id}")
        # # Read the content once and store it

        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None
        if file:
            content_bytes = await file.read()
        else:
            content_bytes = None

        parsed_urls = None
        if url and url.strip():
            try:
                log_info(f"Parsing URL: {url}")
                parsed_urls = json.loads(url)
                log_info(f"Parsed URLs: {parsed_urls}")
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

        source_content = (
            SourceContent(
                content=content_bytes,
                type=file.content_type if file.content_type else None,
            )
            if file
            else None
        )

        source = Source(
            name=name if name else file.filename,
            description=description,
            url=parsed_urls,
            metadata=parsed_metadata,
            content=source_content,
            size=file.size if file else None,
        )

        # Add the processing task to background tasks
        background_tasks.add_task(process_source, knowledge, source_id, source, reader_id)

        # Return immediately with the ID
        return {"source_id": source_id, "status": "processing"}

    @router.patch("/sources/{source_id}", status_code=200)
    async def edit_source(
        source_id: str = Path(..., description="Source ID"),
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON metadata"),
        reader_id: Optional[str] = Form(None),
    ):
        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None
        source = Source(
            id=source_id,
            name=name,
            description=description,
            metadata=parsed_metadata,
        )
        if reader_id:
            if reader_id in knowledge.readers:
                source.reader = knowledge.readers[reader_id]
            else:
                raise HTTPException(status_code=400, detail=f"Invalid reader_id: {reader_id}")
        knowledge.patch_source(source)
        return {"status": "success"}

    @router.get("/sources", response_model=PaginatedResponse[SourceResponseSchema], status_code=200)
    def get_sources(
        limit: Optional[int] = Query(default=20, description="Number of documents to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[SourceResponseSchema]:
        sources, count = knowledge.get_sources(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

        return PaginatedResponse(
            data=[
                SourceResponseSchema(
                    id=source.id,
                    name=source.name,
                    description=source.description,
                    type=source.content.type if source.content else None,
                    size=str(source.size) if source.size else "0",
                    metadata=source.metadata,
                    linked_to=knowledge.name,
                    status=source.status,
                    created_at=str(source.created_at) if source.created_at else None,
                    updated_at=str(source.updated_at) if source.updated_at else None,
                )
                for source in sources
            ],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=count,
                total_pages=math.ceil(count / limit) if limit is not None and limit > 0 else 0,
            ),
        )

    @router.get("/sources/{source_id}", response_model=SourceResponseSchema, status_code=200)
    def get_source_by_id(source_id: str) -> SourceResponseSchema:
        log_info(f"Getting source by id: {source_id}")

        source = knowledge.get_source(source_id=source_id)

        response = SourceResponseSchema(
            id=source_id,
            name=source.name,
            description=source.description,
            type=source.content.type if source.content else None,
            size=str(len(source.content.content)) if source.content else "0",
            linked_to=knowledge.name,
            metadata=source.metadata,
            access_count=0,
            status=source.status,
            created_at=str(source.created_at) if source.created_at else None,
            updated_at=str(source.updated_at) if source.updated_at else None,
        )

        return response

    @router.delete(
        "/sources/{source_id}",
        response_model=SourceResponseSchema,
        status_code=200,
        response_model_exclude_none=True,
    )
    def delete_source_by_id(source_id: str) -> SourceResponseSchema:
        knowledge.remove_source(source_id=source_id)
        log_info(f"Deleting source by id: {source_id}")

        return SourceResponseSchema(
            id=source_id,
        )

    @router.delete("/sources", status_code=200)
    def delete_all_sources():
        log_info(f"Deleting all sources")
        knowledge.remove_all_sources()
        return "success"

    @router.get("/sources/{source_id}/status", status_code=200)
    def get_source_status(source_id: str) -> str:
        log_info(f"Getting source status: {source_id}")
        return knowledge.get_source_status(source_id=source_id)

    @router.get("/config", status_code=200)
    def get_config() -> ConfigResponseSchema:
        readers = knowledge.get_readers()
        return ConfigResponseSchema(
            readers=[ReaderSchema(id=k, name=v.name, description=v.description) for k, v in readers.items()],
            filters=knowledge.get_filters(),
        )

    return router


def process_source(knowledge: Knowledge, source_id: str, source: Source, reader_id: Optional[str] = None):
    """Background task to process the source"""
    log_info(f"Processing source {source_id}")
    try:
        # Set the document ID
        source.id = source_id
        # Process the source
        if reader_id:
            source.reader = knowledge.readers[reader_id]
        knowledge._add_source_from_api(source)
        log_info(f"Source {source_id} processed successfully")
    except Exception as e:
        log_info(f"Error processing source {source_id}: {e}")
        # You might want to update a status in the database here
