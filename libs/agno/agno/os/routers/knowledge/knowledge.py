import json
import logging
import math
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Path, Query, UploadFile

from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader import ReaderFactory
from agno.knowledge.reader.base import Reader
from agno.knowledge.utils import get_all_chunkers_info, get_all_readers_info, get_content_types_to_readers_mapping
from agno.os.auth import get_authentication_dependency
from agno.os.routers.knowledge.schemas import (
    ChunkerSchema,
    ConfigResponseSchema,
    ContentResponseSchema,
    ContentStatus,
    ContentStatusResponse,
    ContentUpdateSchema,
    ReaderSchema,
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
from agno.os.utils import get_knowledge_instance_by_db_id
from agno.utils.log import log_debug, log_info
from agno.utils.string import generate_id

logger = logging.getLogger(__name__)


def get_knowledge_router(
    knowledge_instances: List[Knowledge], settings: AgnoAPISettings = AgnoAPISettings()
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


def attach_routes(router: APIRouter, knowledge_instances: List[Knowledge]) -> APIRouter:
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
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None, description="Content name (auto-generated from file/URL if not provided)"),
        description: Optional[str] = Form(None, description="Content description for context"),
        url: Optional[str] = Form(None, description="URL to fetch content from (JSON array or single URL string)"),
        metadata: Optional[str] = Form(None, description="JSON metadata object for additional content properties"),
        file: Optional[UploadFile] = File(None, description="File to upload for processing"),
        text_content: Optional[str] = Form(None, description="Raw text content to process"),
        reader_id: Optional[str] = Form(None, description="ID of the reader to use for content processing"),
        chunker: Optional[str] = Form(None, description="Chunking strategy to apply during processing"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for content storage"),
    ):
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        log_info(f"Adding content: {name}, {description}, {url}, {metadata}")

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

        background_tasks.add_task(process_content, knowledge, content, reader_id, chunker)

        response = ContentResponseSchema(
            id=content.id,
            name=name,
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
        content_id: str = Path(..., description="Content ID"),
        name: Optional[str] = Form(None, description="Content name"),
        description: Optional[str] = Form(None, description="Content description"),
        metadata: Optional[str] = Form(None, description="Content metadata as JSON string"),
        reader_id: Optional[str] = Form(None, description="ID of the reader to use for processing"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> Optional[ContentResponseSchema]:
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)

        # Parse metadata JSON string if provided
        parsed_metadata = None
        if metadata and metadata.strip():
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON format for metadata")

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

        updated_content_dict = knowledge.patch_content(content)
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
        limit: Optional[int] = Query(default=20, description="Number of content entries to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> PaginatedResponse[ContentResponseSchema]:
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
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
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ContentResponseSchema:
        log_info(f"Getting content by id: {content_id}")
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
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
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ContentResponseSchema:
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        await knowledge.aremove_content_by_id(content_id=content_id)
        log_info(f"Deleting content by id: {content_id}")

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
    def delete_all_content(
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ):
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        log_info("Deleting all content")
        knowledge.remove_all_content()
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
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ContentStatusResponse:
        log_info(f"Getting content status: {content_id}")
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        knowledge_status, status_message = await knowledge.aget_content_status(content_id=content_id)

        # Handle the case where content is not found
        if knowledge_status is None:
            return ContentStatusResponse(
                status=ContentStatus.FAILED, status_message=status_message or "Content not found"
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

        return ContentStatusResponse(status=status, status_message=status_message or "")

    @router.post(
        "/knowledge/search",
        status_code=200,
        operation_id="search_vectors",
        summary="Search Vectors",
        description="Search the knowledge base for relevant vectors using query, filters and search type.",
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
    def search_vectors(request: VectorSearchRequestSchema) -> PaginatedResponse[VectorSearchResult]:
        import time

        start_time = time.time()

        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, request.db_id)

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

        results = knowledge.search(
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
        summary="Get Knowledge Configuration",
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
                                ".csv": ["csv"],
                                ".xlsx": ["csv"],
                                ".xls": ["csv"],
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
                                },
                                "DocumentChunker": {
                                    "key": "DocumentChunker",
                                    "name": "DocumentChunker",
                                    "description": "A chunking strategy that splits text based on document structure like paragraphs and sections",
                                },
                                "RecursiveChunker": {
                                    "key": "RecursiveChunker",
                                    "name": "RecursiveChunker",
                                    "description": "Chunking strategy that recursively splits text into chunks by finding natural break points",
                                },
                                "SemanticChunker": {
                                    "key": "SemanticChunker",
                                    "name": "SemanticChunker",
                                    "description": "Chunking strategy that splits text into semantic chunks using chonkie",
                                },
                                "FixedSizeChunker": {
                                    "key": "FixedSizeChunker",
                                    "name": "FixedSizeChunker",
                                    "description": "Chunking strategy that splits text into fixed-size chunks with optional overlap",
                                },
                                "RowChunker": {
                                    "key": "RowChunker",
                                    "name": "RowChunker",
                                    "description": "RowChunking chunking strategy",
                                },
                                "MarkdownChunker": {
                                    "key": "MarkdownChunker",
                                    "name": "MarkdownChunker",
                                    "description": "A chunking strategy that splits markdown based on structure like headers, paragraphs and sections",
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
    def get_config(
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ConfigResponseSchema:
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)

        # Get factory readers info
        readers_info = get_all_readers_info()
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
        readers_dict: Dict[str, Reader] = knowledge.get_readers() or {}
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

        # Get content types to readers mapping
        types_of_readers = get_content_types_to_readers_mapping()
        chunkers_list = get_all_chunkers_info()

        # Convert chunkers list to dictionary format expected by schema
        chunkers_dict = {}
        for chunker_info in chunkers_list:
            chunker_key = chunker_info.get("key")
            if chunker_key:
                chunkers_dict[chunker_key] = ChunkerSchema(
                    key=chunker_key, name=chunker_info.get("name"), description=chunker_info.get("description")
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

        return ConfigResponseSchema(
            readers=reader_schemas,
            vector_dbs=vector_dbs,
            readersForType=types_of_readers,
            chunkers=chunkers_dict,
            filters=knowledge.get_filters(),
        )

    return router


async def process_content(
    knowledge: Knowledge,
    content: Content,
    reader_id: Optional[str] = None,
    chunker: Optional[str] = None,
):
    """Background task to process the content"""

    try:
        if reader_id:
            reader = None
            if knowledge.readers and reader_id in knowledge.readers:
                reader = knowledge.readers[reader_id]
            else:
                key = reader_id.lower().strip().replace("-", "_").replace(" ", "_")
                candidates = [key] + ([key[:-6]] if key.endswith("reader") else [])
                for cand in candidates:
                    try:
                        reader = ReaderFactory.create_reader(cand)
                        log_debug(f"Resolved reader: {reader.__class__.__name__}")
                        break
                    except Exception:
                        continue
            if reader:
                content.reader = reader
        if chunker and content.reader:
            # Set the chunker name on the reader - let the reader handle it internally
            content.reader.set_chunking_strategy_from_string(chunker)
            log_debug(f"Set chunking strategy: {chunker}")

        log_debug(f"Using reader: {content.reader.__class__.__name__}")
        await knowledge._load_content(content, upsert=False, skip_if_exists=True)
        log_info(f"Content {content.id} processed successfully")
    except Exception as e:
        log_info(f"Error processing content: {e}")
        # Mark content as failed in the contents DB
        try:
            from agno.knowledge.content import ContentStatus as KnowledgeContentStatus

            content.status = KnowledgeContentStatus.FAILED
            content.status_message = str(e)
            knowledge.patch_content(content)
        except Exception:
            # Swallow any secondary errors to avoid crashing the background task
            pass
