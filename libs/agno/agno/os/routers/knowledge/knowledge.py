import json
import logging
import math
from typing import Dict, List, Optional
from uuid import uuid4

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
)
from agno.os.schema import PaginatedResponse, PaginationInfo, SortOrder
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_knowledge_instance_by_db_id
from agno.utils.log import log_debug, log_info

logger = logging.getLogger(__name__)


def get_knowledge_router(
    knowledge_instances: List[Knowledge], settings: AgnoAPISettings = AgnoAPISettings()
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))], tags=["Knowledge"])
    return attach_routes(router=router, knowledge_instances=knowledge_instances)


def attach_routes(router: APIRouter, knowledge_instances: List[Knowledge]) -> APIRouter:
    @router.post("/knowledge/content", response_model=ContentResponseSchema, status_code=202)
    async def upload_content(
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        url: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON metadata"),
        file: Optional[UploadFile] = File(None),
        text_content: Optional[str] = Form(None),
        reader_id: Optional[str] = Form(None),
        chunker: Optional[str] = Form(None),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ):
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
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
        background_tasks.add_task(process_content, knowledge, content_id, content, reader_id, chunker)

        response = ContentResponseSchema(
            id=content_id,
            name=name,
            description=description,
            metadata=parsed_metadata,
            status=ContentStatus.PROCESSING,
        )
        return response

    @router.patch("/knowledge/content/{content_id}", response_model=ContentResponseSchema, status_code=200)
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

    @router.get("/knowledge/content", response_model=PaginatedResponse[ContentResponseSchema], status_code=200)
    def get_content(
        limit: Optional[int] = Query(default=20, description="Number of content entries to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> PaginatedResponse[ContentResponseSchema]:
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        contents, count = knowledge.get_content(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

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

    @router.get("/knowledge/content/{content_id}", response_model=ContentResponseSchema, status_code=200)
    def get_content_by_id(
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ContentResponseSchema:
        log_info(f"Getting content by id: {content_id}")
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        content = knowledge.get_content_by_id(content_id=content_id)
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
    )
    def delete_content_by_id(
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ContentResponseSchema:
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        knowledge.remove_content_by_id(content_id=content_id)
        log_info(f"Deleting content by id: {content_id}")

        return ContentResponseSchema(
            id=content_id,
        )

    @router.delete("/knowledge/content", status_code=200)
    def delete_all_content(
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ):
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        log_info("Deleting all content")
        knowledge.remove_all_content()
        return "success"

    @router.get("/knowledge/content/{content_id}/status", status_code=200, response_model=ContentStatusResponse)
    def get_content_status(
        content_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> ContentStatusResponse:
        log_info(f"Getting content status: {content_id}")
        knowledge = get_knowledge_instance_by_db_id(knowledge_instances, db_id)
        knowledge_status, status_message = knowledge.get_content_status(content_id=content_id)

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

    @router.get("/knowledge/config", status_code=200)
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

        return ConfigResponseSchema(
            readers=reader_schemas,
            readersForType=types_of_readers,
            chunkers=chunkers_dict,
            filters=knowledge.get_filters(),
        )

    return router


async def process_content(
    knowledge: Knowledge,
    content_id: str,
    content: Content,
    reader_id: Optional[str] = None,
    chunker: Optional[str] = None,
):
    """Background task to process the content"""
    log_info(f"Processing content {content_id}")
    try:
        content.id = content_id
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
        log_info(f"Content {content_id} processed successfully")
    except Exception as e:
        log_info(f"Error processing content {content_id}: {e}")
        # Mark content as failed in the contents DB
        try:
            from agno.knowledge.content import ContentStatus as KnowledgeContentStatus

            content.status = KnowledgeContentStatus.FAILED
            content.status_message = str(e)
            content.id = content_id
            knowledge.patch_content(content)
        except Exception:
            # Swallow any secondary errors to avoid crashing the background task
            pass
