import json
import logging
import math
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile

from agno.db.base import AsyncBaseDb
from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader import ReaderFactory
from agno.knowledge.reader.base import Reader
from agno.knowledge.remote_content.config import S3Config
from agno.knowledge.utils import get_all_chunkers_info, get_all_readers_info, get_content_types_to_readers_mapping
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.routers.knowledge.schemas import (
    ChunkerSchema,
    ConfigResponseSchema,
    ContentResponseSchema,
    ContentStatus,
    ContentStatusResponse,
    ContentUpdateSchema,
    ReaderSchema,
    RemoteContentSourceSchema,
    SourceFileSchema,
    SourceFilesResponseSchema,
    SourceFolderSchema,
    VectorDbSchema,
    VectorSearchRequestSchema,
    VectorSearchResult,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SortOrder,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_knowledge_instance
from agno.remote.base import RemoteKnowledge
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.string import generate_id

logger = logging.getLogger(__name__)


def get_knowledge_router(
    knowledge_instances: List[Union[Knowledge, RemoteKnowledge]], settings: AgnoAPISettings = AgnoAPISettings()
) -> APIRouter:
    """Create knowledge router with comprehensive OpenAPI documentation for content management endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Knowledge"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, knowledge_instances=knowledge_instances)


def attach_routes(router: APIRouter, knowledge_instances: List[Union[Knowledge, RemoteKnowledge]]) -> APIRouter:
    @router.post(
        "/knowledge/content",
        response_model=ContentResponseSchema,
        status_code=202,
        operation_id="upload_content",
        summary="Upload Content",
        description=(
            "Upload content to the knowledge base. Supports file uploads, text content, or URLs. "
            "Content is processed asynchronously in the background. Supports custom readers and chunking strategies."
        ),
        responses={
            202: {
                "description": "Content upload accepted for processing",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "content-123",
                            "name": "example-document.pdf",
                            "description": "Sample document for processing",
                            "metadata": {"category": "documentation", "priority": "high"},
                            "status": "processing",
                        }
                    }
                },
            },
            400: {
                "description": "Invalid request - malformed metadata or missing content",
                "model": BadRequestResponse,
            },
            422: {"description": "Validation error in form data", "model": ValidationErrorResponse},
        },
    )
    async def upload_content(
        request: Request,
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None, description="Content name (auto-generated from file/URL if not provided)"),
        description: Optional[str] = Form(None, description="Content description for context"),
        url: Optional[str] = Form(None, description="URL to fetch content from (JSON array or single URL string)"),
        metadata: Optional[str] = Form(None, description="JSON metadata object for additional content properties"),
        file: Optional[UploadFile] = File(None, description="File to upload for processing"),
        text_content: Optional[str] = Form(None, description="Raw text content to process"),
        reader_id: Optional[str] = Form(None, description="ID of the reader to use for content processing"),
        chunker: Optional[str] = Form(None, description="Chunking strategy to apply during processing"),
        chunk_size: Optional[int] = Form(None, description="Chunk size to use for processing"),
        chunk_overlap: Optional[int] = Form(None, description="Chunk overlap to use for processing"),
        backup: Optional[bool] = Form(
            None, description="Store backup content copy. None=auto (store if configured), True=force, False=skip"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for content storage"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to upload to"),
    ):
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None

        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.upload_content(
                name=name,
                description=description,
                url=url,
                metadata=parsed_metadata,
                file=file,
                text_content=text_content,
                reader_id=reader_id,
                chunker=chunker,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                headers=headers,
            )

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
            file_data = FileData(
                content=content_bytes,
                type=file.content_type if file.content_type else None,
                filename=file.filename,
                size=file.size,
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
        content_hash = knowledge._build_content_hash(content)
        content.content_hash = content_hash
        content.id = generate_id(content_hash)

        background_tasks.add_task(
            process_content, knowledge, content, reader_id, chunker, chunk_size, chunk_overlap, backup
        )

        response = ContentResponseSchema(
            id=content.id,
            name=name,
            description=description,
            metadata=parsed_metadata,
            status=ContentStatus.PROCESSING,
        )
        return response

    @router.post(
        "/knowledge/remote-content",
        response_model=ContentResponseSchema,
        status_code=202,
        operation_id="upload_remote_content",
        summary="Upload Remote Content",
        description=(
            "Upload content from a remote source (S3, GCS, SharePoint, GitHub) to the knowledge base. "
            "Content is processed asynchronously in the background. "
        ),
        responses={
            202: {
                "description": "Remote content upload accepted for processing",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "content-456",
                            "name": "reports/q1-2024.pdf",
                            "description": "Q1 Report from S3",
                            "metadata": {"source": "s3-docs"},
                            "status": "processing",
                        }
                    }
                },
            },
            400: {
                "description": "Invalid request - unknown config or missing path",
                "model": BadRequestResponse,
            },
            422: {"description": "Validation error in request body", "model": ValidationErrorResponse},
        },
    )
    async def upload_remote_content(
        request: Request,
        background_tasks: BackgroundTasks,
        config_id: str = Form(..., description="ID of the configured remote content source (from /knowledge/config)"),
        path: str = Form(..., description="Path to file or folder in the remote source"),
        name: Optional[str] = Form(None, description="Content name (auto-generated if not provided)"),
        description: Optional[str] = Form(None, description="Content description"),
        metadata: Optional[str] = Form(None, description="JSON metadata object"),
        reader_id: Optional[str] = Form(None, description="ID of the reader to use for processing"),
        chunker: Optional[str] = Form(None, description="Chunking strategy to apply"),
        chunk_size: Optional[int] = Form(None, description="Chunk size for processing"),
        chunk_overlap: Optional[int] = Form(None, description="Chunk overlap for processing"),
        backup: Optional[bool] = Form(
            None, description="Store backup content copy. None=auto (store if configured), True=force, False=skip"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for content storage"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to upload to"),
    ):
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            # TODO: Forward to remote knowledge instance
            raise HTTPException(status_code=501, detail="Remote content upload not yet supported for RemoteKnowledge")

        # Validate that the config_id exists in configured sources
        config = knowledge._get_remote_config_by_id(config_id)
        if config is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown content source: {config_id}. Check /knowledge/config for available sources.",
            )

        # Parse metadata if provided
        parsed_metadata = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                parsed_metadata = {"value": metadata}

        # Use the config's factory methods to create the remote content object
        # If path ends with '/', treat as folder, otherwise treat as file
        is_folder = path.endswith("/")
        if is_folder:
            if hasattr(config, "folder"):
                remote_content = config.folder(path.rstrip("/"))
            else:
                raise HTTPException(status_code=400, detail=f"Config {config_id} does not support folder uploads")
        else:
            if hasattr(config, "file"):
                remote_content = config.file(path)
            else:
                raise HTTPException(status_code=400, detail=f"Config {config_id} does not support file uploads")

        # Set name from path if not provided
        content_name = name or path

        content = Content(
            name=content_name,
            description=description,
            metadata=parsed_metadata,
            remote_content=remote_content,
        )
        content_hash = knowledge._build_content_hash(content)
        content.content_hash = content_hash
        content.id = generate_id(content_hash)

        background_tasks.add_task(
            process_content, knowledge, content, reader_id, chunker, chunk_size, chunk_overlap, backup
        )

        response = ContentResponseSchema(
            id=content.id,
            name=content_name,
            description=description,
            metadata=parsed_metadata,
            status=ContentStatus.PROCESSING,
        )
        return response

    @router.patch(
        "/knowledge/content/{content_id}",
        response_model=ContentResponseSchema,
        status_code=200,
        operation_id="update_content",
        summary="Update Content",
        description=(
            "Update content properties such as name, description, metadata, or processing configuration. "
            "Allows modification of existing content without re-uploading."
        ),
        responses={
            200: {
                "description": "Content updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "3c2fc685-d451-4d47-b0c0-b9a544c672b7",
                            "name": "example.pdf",
                            "description": "",
                            "type": "application/pdf",
                            "size": "251261",
                            "linked_to": None,
                            "metadata": {},
                            "access_count": 1,
                            "status": "completed",
                            "status_message": "",
                            "created_at": "2025-09-08T15:22:53Z",
                            "updated_at": "2025-09-08T15:22:54Z",
                        }
                    }
                },
            },
            400: {
                "description": "Invalid request - malformed metadata or invalid reader_id",
                "model": BadRequestResponse,
            },
            404: {"description": "Content not found", "model": NotFoundResponse},
        },
    )
    async def update_content(
        request: Request,
        content_id: str = Path(..., description="Content ID"),
        name: Optional[str] = Form(None, description="Content name"),
        description: Optional[str] = Form(None, description="Content description"),
        metadata: Optional[str] = Form(None, description="Content metadata as JSON string"),
        reader_id: Optional[str] = Form(None, description="ID of the reader to use for processing"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ) -> Optional[ContentResponseSchema]:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        # Parse metadata JSON string if provided
        parsed_metadata = None
        if metadata and metadata.strip():
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON format for metadata")

        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.update_content(
                content_id=content_id,
                name=name,
                description=description,
                metadata=parsed_metadata,
                reader_id=reader_id,
                headers=headers,
            )

        # Create ContentUpdateSchema object from form data
        update_data = ContentUpdateSchema(
            name=name if name and name.strip() else None,
            description=description if description and description.strip() else None,
            metadata=parsed_metadata,
            reader_id=reader_id if reader_id and reader_id.strip() else None,
        )

        content = Content(
            id=content_id,
            name=update_data.name,
            description=update_data.description,
            metadata=update_data.metadata,
        )

        if update_data.reader_id:
            if knowledge.readers and update_data.reader_id in knowledge.readers:
                content.reader = knowledge.readers[update_data.reader_id]
            else:
                raise HTTPException(status_code=400, detail=f"Invalid reader_id: {update_data.reader_id}")

        # Use async patch method if contents_db is an AsyncBaseDb, otherwise use sync patch method
        updated_content_dict = None
        try:
            if knowledge.contents_db is not None and isinstance(knowledge.contents_db, AsyncBaseDb):
                updated_content_dict = await knowledge.apatch_content(content)
            else:
                updated_content_dict = knowledge.patch_content(content)
        except Exception as e:
            log_error(f"Error updating content: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error updating content: {str(e)}")

        if not updated_content_dict:
            raise HTTPException(status_code=404, detail=f"Content not found: {content_id}")

        return ContentResponseSchema.from_dict(updated_content_dict)

    @router.get(
        "/knowledge/content",
        response_model=PaginatedResponse[ContentResponseSchema],
        status_code=200,
        operation_id="get_content",
        summary="List Content",
        description=(
            "Retrieve paginated list of all content in the knowledge base with filtering and sorting options. "
            "Filter by status, content type, or metadata properties."
        ),
        responses={
            200: {
                "description": "Content list retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "id": "3c2fc685-d451-4d47-b0c0-b9a544c672b7",
                                    "name": "example.pdf",
                                    "description": "",
                                    "type": "application/pdf",
                                    "size": "251261",
                                    "linked_to": None,
                                    "metadata": {},
                                    "access_count": 1,
                                    "status": "completed",
                                    "status_message": "",
                                    "created_at": "2025-09-08T15:22:53Z",
                                    "updated_at": "2025-09-08T15:22:54Z",
                                },
                            ],
                            "meta": {"page": 1, "limit": 20, "total_pages": 1, "total_count": 2},
                        }
                    }
                },
            }
        },
    )
    async def get_content(
        request: Request,
        limit: Optional[int] = Query(default=20, description="Number of content entries to return", ge=1),
        page: Optional[int] = Query(default=1, description="Page number", ge=0),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ) -> PaginatedResponse[ContentResponseSchema]:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.get_content(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order.value if sort_order else None,
                headers=headers,
            )

        contents, count = await knowledge.aget_content(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

        return PaginatedResponse(
            data=[
                ContentResponseSchema.from_dict(
                    {
                        "id": content.id,
                        "name": content.name,
                        "description": content.description,
                        "file_type": content.file_type,
                        "size": content.size,
                        "metadata": content.metadata,
                        "status": content.status,
                        "status_message": content.status_message,
                        "created_at": content.created_at,
                        "updated_at": content.updated_at,
                    }
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

    @router.get(
        "/knowledge/content/{content_id}",
        response_model=ContentResponseSchema,
        status_code=200,
        operation_id="get_content_by_id",
        summary="Get Content by ID",
        description="Retrieve detailed information about a specific content item including processing status and metadata.",
        responses={
            200: {
                "description": "Content details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "3c2fc685-d451-4d47-b0c0-b9a544c672b7",
                            "name": "example.pdf",
                            "description": "",
                            "type": "application/pdf",
                            "size": "251261",
                            "linked_to": None,
                            "metadata": {},
                            "access_count": 1,
                            "status": "completed",
                            "status_message": "",
                            "created_at": "2025-09-08T15:22:53Z",
                            "updated_at": "2025-09-08T15:22:54Z",
                        }
                    }
                },
            },
            404: {"description": "Content not found", "model": NotFoundResponse},
        },
    )
    async def get_content_by_id(
        request: Request,
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ) -> ContentResponseSchema:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)
        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.get_content_by_id(content_id=content_id, headers=headers)

        content = await knowledge.aget_content_by_id(content_id=content_id)
        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {content_id}")
        response = ContentResponseSchema.from_dict(
            {
                "id": content_id,
                "name": content.name,
                "description": content.description,
                "file_type": content.file_type,
                "size": len(content.file_data.content) if content.file_data and content.file_data.content else 0,
                "metadata": content.metadata,
                "status": content.status,
                "status_message": content.status_message,
                "created_at": content.created_at,
                "updated_at": content.updated_at,
            }
        )

        return response

    @router.delete(
        "/knowledge/content/{content_id}",
        response_model=ContentResponseSchema,
        status_code=200,
        response_model_exclude_none=True,
        operation_id="delete_content_by_id",
        summary="Delete Content by ID",
        description="Permanently remove a specific content item from the knowledge base. This action cannot be undone.",
        responses={
            200: {},
            404: {"description": "Content not found", "model": NotFoundResponse},
            500: {"description": "Failed to delete content", "model": InternalServerErrorResponse},
        },
    )
    async def delete_content_by_id(
        request: Request,
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ) -> ContentResponseSchema:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)
        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            await knowledge.delete_content_by_id(content_id=content_id, headers=headers)
        else:
            await knowledge.aremove_content_by_id(content_id=content_id)

        return ContentResponseSchema(
            id=content_id,
        )

    @router.delete(
        "/knowledge/content",
        status_code=200,
        operation_id="delete_all_content",
        summary="Delete All Content",
        description=(
            "Permanently remove all content from the knowledge base. This is a destructive operation that "
            "cannot be undone. Use with extreme caution."
        ),
        responses={
            200: {},
            500: {"description": "Failed to delete all content", "model": InternalServerErrorResponse},
        },
    )
    async def delete_all_content(
        request: Request,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ):
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)
        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.delete_all_content(headers=headers)

        await knowledge.aremove_all_content()
        return "success"

    @router.get(
        "/knowledge/content/{content_id}/status",
        status_code=200,
        response_model=ContentStatusResponse,
        operation_id="get_content_status",
        summary="Get Content Status",
        description=(
            "Retrieve the current processing status of a content item. Useful for monitoring "
            "asynchronous content processing progress and identifying any processing errors."
        ),
        responses={
            200: {
                "description": "Content status retrieved successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "completed": {
                                "summary": "Example completed content status",
                                "value": {
                                    "status": "completed",
                                    "status_message": "",
                                },
                            }
                        }
                    }
                },
            },
            404: {"description": "Content not found", "model": NotFoundResponse},
        },
    )
    async def get_content_status(
        request: Request,
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ) -> ContentStatusResponse:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)
        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.get_content_status(content_id=content_id, headers=headers)

        knowledge_status, status_message = await knowledge.aget_content_status(content_id=content_id)

        # Handle the case where content is not found
        if knowledge_status is None:
            return ContentStatusResponse(
                id=content_id, status=ContentStatus.FAILED, status_message=status_message or "Content not found"
            )

        # Convert knowledge ContentStatus to schema ContentStatus (they have same values)
        if hasattr(knowledge_status, "value"):
            status_value = knowledge_status.value
        else:
            status_value = str(knowledge_status)

        # Convert string status to ContentStatus enum if needed (for backward compatibility and mocks)
        if isinstance(status_value, str):
            try:
                status = ContentStatus(status_value.lower())
            except ValueError:
                # Handle legacy or unknown statuses gracefully
                if "failed" in status_value.lower():
                    status = ContentStatus.FAILED
                elif "completed" in status_value.lower():
                    status = ContentStatus.COMPLETED
                else:
                    status = ContentStatus.PROCESSING
        else:
            status = ContentStatus.PROCESSING

        return ContentStatusResponse(id=content_id, status=status, status_message=status_message or "")

    @router.post(
        "/knowledge/search",
        status_code=200,
        operation_id="search_knowledge",
        summary="Search Knowledge",
        description="Search the knowledge base for relevant documents using query, filters and search type.",
        response_model=PaginatedResponse[VectorSearchResult],
        responses={
            200: {
                "description": "Search results retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "id": "doc_123",
                                    "content": "Jordan Mitchell - Software Engineer with skills in JavaScript, React, Python",
                                    "name": "cv_1",
                                    "meta_data": {"page": 1, "chunk": 1},
                                    "usage": {"total_tokens": 14},
                                    "reranking_score": 0.95,
                                    "content_id": "content_456",
                                }
                            ],
                            "meta": {"page": 1, "limit": 20, "total_pages": 2, "total_count": 35},
                        }
                    }
                },
            },
            400: {"description": "Invalid search parameters"},
            404: {"description": "No documents found"},
        },
    )
    async def search_knowledge(
        http_request: Request, request: VectorSearchRequestSchema
    ) -> PaginatedResponse[VectorSearchResult]:
        import time

        start_time = time.time()

        knowledge = get_knowledge_instance(knowledge_instances, request.db_id, request.knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(http_request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.search_knowledge(
                query=request.query,
                max_results=request.max_results,
                filters=request.filters,
                search_type=request.search_type,
                headers=headers,
            )

        # For now, validate the vector db ids exist in the knowledge base
        # We will add more logic around this once we have multi vectordb support
        # If vector db ids are provided, check if any of them match the knowledge's vector db
        if request.vector_db_ids:
            if knowledge.vector_db and knowledge.vector_db.id:
                if knowledge.vector_db.id not in request.vector_db_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"None of the provided Vector DB IDs {request.vector_db_ids} match the knowledge base Vector DB ID {knowledge.vector_db.id}",
                    )
            else:
                raise HTTPException(status_code=400, detail="Knowledge base has no vector database configured")

        # Calculate pagination parameters
        meta = request.meta
        limit = meta.limit if meta and meta.limit is not None else 20
        page = meta.page if meta and meta.page is not None else 1

        # Use max_results if specified, otherwise use a higher limit for search then paginate
        search_limit = request.max_results

        results = await knowledge.asearch(
            query=request.query, max_results=search_limit, filters=request.filters, search_type=request.search_type
        )

        # Calculate pagination
        total_results = len(results)
        start_idx = (page - 1) * limit

        # Ensure start_idx doesn't exceed the total results
        if start_idx >= total_results and total_results > 0:
            # If page is beyond available results, return empty results
            paginated_results = []
        else:
            end_idx = min(start_idx + limit, total_results)
            paginated_results = results[start_idx:end_idx]

        search_time_ms = (time.time() - start_time) * 1000

        # Convert Document objects to serializable format
        document_results = [VectorSearchResult.from_document(doc) for doc in paginated_results]

        # Calculate pagination info
        total_pages = (total_results + limit - 1) // limit  # Ceiling division

        return PaginatedResponse(
            data=document_results,
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_results,
                search_time_ms=search_time_ms,
            ),
        )

    @router.get(
        "/knowledge/config",
        status_code=200,
        operation_id="get_knowledge_config",
        summary="Get Config",
        description=(
            "Retrieve available readers, chunkers, and configuration options for content processing. "
            "This endpoint provides metadata about supported file types, processing strategies, and filters."
        ),
        responses={
            200: {
                "description": "Knowledge configuration retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "readers": {
                                "website": {
                                    "id": "website",
                                    "name": "WebsiteReader",
                                    "description": "Reads website files",
                                    "chunkers": [
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                        "FixedSizeChunker",
                                    ],
                                },
                                "firecrawl": {
                                    "id": "firecrawl",
                                    "name": "FirecrawlReader",
                                    "description": "Reads firecrawl files",
                                    "chunkers": [
                                        "SemanticChunker",
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                    ],
                                },
                                "youtube": {
                                    "id": "youtube",
                                    "name": "YoutubeReader",
                                    "description": "Reads youtube files",
                                    "chunkers": [
                                        "RecursiveChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "SemanticChunker",
                                        "FixedSizeChunker",
                                    ],
                                },
                                "web_search": {
                                    "id": "web_search",
                                    "name": "WebSearchReader",
                                    "description": "Reads web_search files",
                                    "chunkers": [
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                        "FixedSizeChunker",
                                    ],
                                },
                                "arxiv": {
                                    "id": "arxiv",
                                    "name": "ArxivReader",
                                    "description": "Reads arxiv files",
                                    "chunkers": [
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                    ],
                                },
                                "csv": {
                                    "id": "csv",
                                    "name": "CsvReader",
                                    "description": "Reads csv files",
                                    "chunkers": [
                                        "RowChunker",
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                    ],
                                },
                                "docx": {
                                    "id": "docx",
                                    "name": "DocxReader",
                                    "description": "Reads docx files",
                                    "chunkers": [
                                        "DocumentChunker",
                                        "FixedSizeChunker",
                                        "SemanticChunker",
                                        "AgenticChunker",
                                        "RecursiveChunker",
                                    ],
                                },
                                "gcs": {
                                    "id": "gcs",
                                    "name": "GcsReader",
                                    "description": "Reads gcs files",
                                    "chunkers": [
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                    ],
                                },
                                "json": {
                                    "id": "json",
                                    "name": "JsonReader",
                                    "description": "Reads json files",
                                    "chunkers": [
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                    ],
                                },
                                "markdown": {
                                    "id": "markdown",
                                    "name": "MarkdownReader",
                                    "description": "Reads markdown files",
                                    "chunkers": [
                                        "MarkdownChunker",
                                        "DocumentChunker",
                                        "AgenticChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                        "FixedSizeChunker",
                                    ],
                                },
                                "pdf": {
                                    "id": "pdf",
                                    "name": "PdfReader",
                                    "description": "Reads pdf files",
                                    "chunkers": [
                                        "DocumentChunker",
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "SemanticChunker",
                                        "RecursiveChunker",
                                    ],
                                },
                                "text": {
                                    "id": "text",
                                    "name": "TextReader",
                                    "description": "Reads text files",
                                    "chunkers": [
                                        "CodeChunker",
                                        "FixedSizeChunker",
                                        "AgenticChunker",
                                        "DocumentChunker",
                                        "RecursiveChunker",
                                        "SemanticChunker",
                                    ],
                                },
                            },
                            "readersForType": {
                                "url": [
                                    "url",
                                    "website",
                                    "firecrawl",
                                    "youtube",
                                    "web_search",
                                    "gcs",
                                ],
                                "youtube": ["youtube"],
                                "text": ["web_search"],
                                "topic": ["arxiv"],
                                "file": ["csv", "gcs"],
                                ".csv": ["csv", "field_labeled_csv"],
                                ".xlsx": ["excel"],
                                ".xls": ["excel"],
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ["excel"],
                                "application/vnd.ms-excel": ["excel"],
                                ".docx": ["docx"],
                                ".doc": ["docx"],
                                ".json": ["json"],
                                ".md": ["markdown"],
                                ".pdf": ["pdf"],
                                ".txt": ["text"],
                            },
                            "chunkers": {
                                "AgenticChunker": {
                                    "key": "AgenticChunker",
                                    "name": "AgenticChunker",
                                    "description": "Chunking strategy that uses an LLM to determine natural breakpoints in the text",
                                    "metadata": {"chunk_size": 5000},
                                },
                                "CodeChunker": {
                                    "key": "CodeChunker",
                                    "name": "CodeChunker",
                                    "description": "The CodeChunker splits code into chunks based on its structure, leveraging Abstract Syntax Trees (ASTs) to create contextually relevant segments",
                                    "metadata": {"chunk_size": 2048},
                                },
                                "DocumentChunker": {
                                    "key": "DocumentChunker",
                                    "name": "DocumentChunker",
                                    "description": "A chunking strategy that splits text based on document structure like paragraphs and sections",
                                    "metadata": {
                                        "chunk_size": 5000,
                                        "chunk_overlap": 0,
                                    },
                                },
                                "FixedSizeChunker": {
                                    "key": "FixedSizeChunker",
                                    "name": "FixedSizeChunker",
                                    "description": "Chunking strategy that splits text into fixed-size chunks with optional overlap",
                                    "metadata": {
                                        "chunk_size": 5000,
                                        "chunk_overlap": 0,
                                    },
                                },
                                "MarkdownChunker": {
                                    "key": "MarkdownChunker",
                                    "name": "MarkdownChunker",
                                    "description": "A chunking strategy that splits markdown based on structure like headers, paragraphs and sections",
                                    "metadata": {
                                        "chunk_size": 5000,
                                        "chunk_overlap": 0,
                                    },
                                },
                                "RecursiveChunker": {
                                    "key": "RecursiveChunker",
                                    "name": "RecursiveChunker",
                                    "description": "Chunking strategy that recursively splits text into chunks by finding natural break points",
                                    "metadata": {
                                        "chunk_size": 5000,
                                        "chunk_overlap": 0,
                                    },
                                },
                                "RowChunker": {
                                    "key": "RowChunker",
                                    "name": "RowChunker",
                                    "description": "RowChunking chunking strategy",
                                    "metadata": {},
                                },
                                "SemanticChunker": {
                                    "key": "SemanticChunker",
                                    "name": "SemanticChunker",
                                    "description": "Chunking strategy that splits text into semantic chunks using chonkie",
                                    "metadata": {"chunk_size": 5000},
                                },
                            },
                            "vector_dbs": [
                                {
                                    "id": "vector_db_1",
                                    "name": "Vector DB 1",
                                    "description": "Vector DB 1 description",
                                    "search_types": ["vector", "keyword", "hybrid"],
                                }
                            ],
                            "filters": ["filter_tag_1", "filter_tag2"],
                        }
                    }
                },
            }
        },
    )
    async def get_config(
        request: Request,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID to use"),
    ) -> ConfigResponseSchema:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await knowledge.get_config(headers=headers)

        # Get factory readers info (including custom readers from this knowledge instance)
        readers_info = get_all_readers_info(knowledge)
        reader_schemas = {}
        # Add factory readers
        for reader_info in readers_info:
            reader_schemas[reader_info["id"]] = ReaderSchema(
                id=reader_info["id"],
                name=reader_info["name"],
                description=reader_info.get("description"),
                chunkers=reader_info.get("chunking_strategies", []),
            )

        # Add custom readers from knowledge.readers
        readers_result: Any = knowledge.get_readers() or {}
        # Ensure readers_dict is a dictionary (defensive check)
        if not isinstance(readers_result, dict):
            readers_dict: Dict[str, Reader] = {}
        else:
            readers_dict = readers_result
        if readers_dict:
            for reader_id, reader in readers_dict.items():
                # Get chunking strategies from the reader
                chunking_strategies = []
                try:
                    strategies = reader.get_supported_chunking_strategies()
                    chunking_strategies = [strategy.value for strategy in strategies]
                except Exception:
                    chunking_strategies = []

                # Check if this reader ID already exists in factory readers
                if reader_id not in reader_schemas:
                    reader_schemas[reader_id] = ReaderSchema(
                        id=reader_id,
                        name=getattr(reader, "name", reader.__class__.__name__),
                        description=getattr(reader, "description", f"Custom {reader.__class__.__name__}"),
                        chunkers=chunking_strategies,
                    )

        # Get content types to readers mapping (including custom readers from this knowledge instance)
        types_of_readers = get_content_types_to_readers_mapping(knowledge)
        chunkers_list = get_all_chunkers_info()

        # Convert chunkers list to dictionary format expected by schema
        chunkers_dict = {}
        for chunker_info in chunkers_list:
            chunker_key = chunker_info.get("key")
            if chunker_key:
                chunkers_dict[chunker_key] = ChunkerSchema(
                    key=chunker_key,
                    name=chunker_info.get("name"),
                    description=chunker_info.get("description"),
                    metadata=chunker_info.get("metadata", {}),
                )

        vector_dbs = []
        if knowledge.vector_db:
            search_types = knowledge.vector_db.get_supported_search_types()
            name = knowledge.vector_db.name
            db_id = knowledge.vector_db.id
            vector_dbs.append(
                VectorDbSchema(
                    id=db_id,
                    name=name,
                    description=knowledge.vector_db.description,
                    search_types=search_types,
                )
            )
        filters = await knowledge.aget_valid_filters()

        # Get remote content sources if available
        remote_content_sources = None
        if hasattr(knowledge, "_get_remote_configs") and callable(knowledge._get_remote_configs):
            remote_configs = knowledge._get_remote_configs()
            if remote_configs:
                from agno.os.routers.knowledge.schemas import RemoteContentSourceSchema

                remote_content_sources = [
                    RemoteContentSourceSchema(
                        id=config.id,
                        name=config.name,
                        type=config.__class__.__name__.replace("Config", "").lower(),
                        metadata=config.metadata,
                    )
                    for config in remote_configs
                ]
        return ConfigResponseSchema(
            readers=reader_schemas,
            vector_dbs=vector_dbs,
            readersForType=types_of_readers,
            chunkers=chunkers_dict,
            filters=filters,
            remote_content_sources=remote_content_sources,
        )

    @router.get(
        "/knowledge/{knowledge_id}/sources",
        response_model=List[RemoteContentSourceSchema],
        status_code=200,
        operation_id="list_content_sources",
        summary="List Content Sources",
        description="List all registered content sources (S3, GCS, SharePoint, GitHub) for the knowledge base.",
        responses={
            200: {
                "description": "Content sources retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "company-s3",
                                "name": "Company Documents",
                                "type": "s3",
                                "prefix": "documents/",
                            }
                        ]
                    }
                },
            },
            404: {"description": "Knowledge base not found", "model": NotFoundResponse},
        },
    )
    async def list_sources(
        request: Request,
        knowledge_id: str = Path(..., description="ID of the knowledge base"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> List[RemoteContentSourceSchema]:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            raise HTTPException(status_code=501, detail="Source listing not yet supported for RemoteKnowledge")

        if not hasattr(knowledge, "_get_remote_configs") or not callable(knowledge._get_remote_configs):
            return []

        remote_configs = knowledge._get_remote_configs()
        if not remote_configs:
            return []

        return [
            RemoteContentSourceSchema(
                id=config.id,
                name=config.name,
                type=config.__class__.__name__.replace("Config", "").lower(),
                prefix=getattr(config, "prefix", None),
            )
            for config in remote_configs
        ]

    @router.get(
        "/knowledge/{knowledge_id}/sources/{source_id}/files",
        response_model=SourceFilesResponseSchema,
        status_code=200,
        operation_id="list_source_files",
        summary="List Files in Source",
        description=(
            "List available files and folders in a specific content source. Supports pagination and folder navigation."
        ),
        responses={
            200: {
                "description": "Files listed successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "source_id": "company-s3",
                            "source_name": "Company Documents",
                            "prefix": "reports/",
                            "folders": [{"prefix": "reports/2024/", "name": "2024", "is_empty": False}],
                            "files": [
                                {
                                    "key": "reports/annual-summary.pdf",
                                    "name": "annual-summary.pdf",
                                    "size": 102400,
                                    "last_modified": "2024-01-15T10:30:00Z",
                                    "content_type": "application/pdf",
                                }
                            ],
                            "meta": {"page": 1, "limit": 100, "total_pages": 1, "total_count": 1},
                        }
                    }
                },
            },
            404: {"description": "Knowledge base or content source not found", "model": NotFoundResponse},
            400: {"description": "Unsupported source type", "model": BadRequestResponse},
        },
    )
    async def list_source_files(
        request: Request,
        knowledge_id: str = Path(..., description="ID of the knowledge base"),
        source_id: str = Path(..., description="ID of the content source"),
        prefix: Optional[str] = Query(default=None, description="Path prefix to filter files"),
        limit: int = Query(default=100, ge=1, le=1000, description="Number of files per page"),
        page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
        delimiter: str = Query(default="/", description="Folder delimiter (enables folder grouping)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> SourceFilesResponseSchema:
        knowledge = get_knowledge_instance(knowledge_instances, db_id, knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            raise HTTPException(status_code=501, detail="Source file listing not yet supported for RemoteKnowledge")

        # Get the config for this source
        config = knowledge._get_remote_config_by_id(source_id)
        if config is None:
            raise HTTPException(status_code=404, detail=f"Content source not found: {source_id}")

        # Only S3 sources support file listing
        if not isinstance(config, S3Config):
            raise HTTPException(
                status_code=400,
                detail=f"Source type '{type(config).__name__}' does not support file listing.",
            )

        try:
            result = config.list_files(
                prefix=prefix,
                delimiter=delimiter,
                limit=limit,
                page=page,
            )
        except ImportError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            error_str = str(e)
            if "NoSuchBucket" in error_str:
                raise HTTPException(
                    status_code=404,
                    detail=f"Bucket '{config.bucket_name}' does not exist",
                )
            if "NoCredentials" in error_str or "InvalidAccessKeyId" in error_str:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing AWS credentials for this source",
                )
            log_error(f"Error listing files from {type(config).__name__}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list files: {error_str}")

        return SourceFilesResponseSchema(
            source_id=source_id,
            source_name=config.name,
            prefix=prefix or "",
            folders=[
                SourceFolderSchema(
                    prefix=folder["prefix"],
                    name=folder["name"],
                    is_empty=folder["is_empty"],
                )
                for folder in result.folders
            ],
            files=[
                SourceFileSchema(
                    key=file["key"],
                    name=file["name"],
                    size=file["size"],
                    last_modified=file["last_modified"],
                    content_type=file["content_type"],
                )
                for file in result.files
            ],
            meta=PaginationInfo(
                page=result.page,
                limit=result.limit,
                total_count=result.total_count,
                total_pages=result.total_pages,
            ),
        )

    @router.post(
        "/knowledge/content/{content_id}/refresh",
        response_model=ContentStatusResponse,
        status_code=202,
        operation_id="refresh_content",
        summary="Refresh Content",
        description=(
            "Refresh content by re-fetching from its original source and re-embedding. "
            "Sources are resolved in priority order: original cloud source first, then backup storage as fallback. "
            "Use cases: embeddings lost, switching embedding model, or source content updated."
        ),
        responses={
            202: {
                "description": "Content refresh accepted for processing",
            },
            400: {
                "description": "Cannot refresh - no source available",
                "model": BadRequestResponse,
            },
            404: {"description": "Content not found", "model": NotFoundResponse},
        },
    )
    async def refresh_content(
        request: Request,
        background_tasks: BackgroundTasks,
        content_id: str = Path(..., description="Content ID to refresh"),
        knowledge_id: Optional[str] = Query(default=None, description="Knowledge base ID (name)"),
    ) -> ContentStatusResponse:
        knowledge = get_knowledge_instance(knowledge_instances, knowledge_id=knowledge_id)

        if isinstance(knowledge, RemoteKnowledge):
            raise HTTPException(status_code=501, detail="Content refresh not yet supported for RemoteKnowledge")

        # Verify content exists
        content = await knowledge.aget_content_by_id(content_id=content_id)
        if not content:
            raise HTTPException(status_code=404, detail=f"Content not found: {content_id}")

        # Verify there is a source to refresh from
        agno_meta = (content.metadata or {}).get(Knowledge.RESERVED_METADATA_KEY, {})
        if not isinstance(agno_meta, dict):
            agno_meta = {}

        has_raw = bool(agno_meta.get("backup_storage_type"))
        has_source = bool(agno_meta.get("source_type"))
        # Also check top-level metadata for backward compatibility
        has_legacy_source = bool(content.metadata and content.metadata.get("source_type"))

        if not has_raw and not has_source and not has_legacy_source:
            raise HTTPException(
                status_code=400,
                detail="Cannot refresh: no backup storage or original source available",
            )

        # Mark as processing
        from agno.knowledge.content import ContentStatus as KnowledgeContentStatus

        content.status = KnowledgeContentStatus.PROCESSING
        content.status_message = "refreshing"
        await knowledge.apatch_content(content)

        background_tasks.add_task(process_refresh, knowledge, content_id)

        return ContentStatusResponse(
            id=content_id,
            status=ContentStatus.PROCESSING,
            status_message="refreshing",
        )

    return router


async def process_refresh(knowledge: Knowledge, content_id: str):
    """Background task to refresh content by re-fetching and re-embedding."""
    try:
        await knowledge.arefresh_content(content_id)
        log_info(f"Content {content_id} refreshed successfully")
    except Exception as e:
        log_error(f"Error refreshing content {content_id}: {e}")
        try:
            from agno.knowledge.content import ContentStatus as KnowledgeContentStatus

            content = await knowledge.aget_content_by_id(content_id)
            if content:
                # Content still has valid vectors — keep COMPLETED status
                # but remove refresh_available since the source is no longer accessible
                content.status = KnowledgeContentStatus.COMPLETED
                content.status_message = f"refresh_failed: {e}"
                if knowledge.contents_db is not None and isinstance(knowledge.contents_db, AsyncBaseDb):
                    await knowledge.apatch_content(content)
                else:
                    knowledge.patch_content(content)
        except Exception:
            pass


async def process_content(
    knowledge: Knowledge,
    content: Content,
    reader_id: Optional[str] = None,
    chunker: Optional[str] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    backup: Optional[bool] = None,
):
    """Background task to process the content"""

    try:
        if reader_id:
            reader = None
            # Use get_readers() to ensure we get a dict (handles list conversion)
            custom_readers = knowledge.get_readers()
            if custom_readers and reader_id in custom_readers:
                reader = custom_readers[reader_id]
                log_debug(f"Found custom reader: {reader.__class__.__name__}")
            else:
                # Try to resolve from factory readers
                key = reader_id.lower().strip().replace("-", "_").replace(" ", "_")
                candidates = [key] + ([key[:-6]] if key.endswith("reader") else [])
                for cand in candidates:
                    try:
                        reader = ReaderFactory.create_reader(cand)
                        log_debug(f"Resolved reader from factory: {reader.__class__.__name__}")
                        break
                    except Exception:
                        continue
            if reader:
                content.reader = reader
            else:
                log_debug(f"Could not resolve reader with id: {reader_id}")
        if chunker and content.reader:
            # Set the chunker name on the reader - let the reader handle it internally
            content.reader.set_chunking_strategy_from_string(chunker, chunk_size=chunk_size, overlap=chunk_overlap)
            log_debug(f"Set chunking strategy: {chunker}")

        log_debug(f"Using reader: {content.reader.__class__.__name__}")
        await knowledge._aload_content(content, upsert=False, skip_if_exists=True, backup=backup)
        log_info(f"Content {content.id} processed successfully")
    except Exception as e:
        log_info(f"Error processing content: {e}")
        # Mark content as failed in the contents DB
        try:
            from agno.knowledge.content import ContentStatus as KnowledgeContentStatus

            content.status = KnowledgeContentStatus.FAILED
            content.status_message = str(e)
            # Use async patch method if contents_db is an AsyncBaseDb, otherwise use sync patch method
            if knowledge.contents_db is not None and isinstance(knowledge.contents_db, AsyncBaseDb):
                await knowledge.apatch_content(content)
            else:
                knowledge.patch_content(content)

        except Exception:
            # Swallow any secondary errors to avoid crashing the background task
            pass
