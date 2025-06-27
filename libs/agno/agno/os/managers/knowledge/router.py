import json
import math
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile

from agno.document.document_v2 import DocumentContent, DocumentV2
from agno.knowledge.knowledge import Knowledge
from agno.os.managers.knowledge.schemas import DocumentResponseSchema
from agno.os.managers.utils import PaginatedResponse, PaginationInfo, SortOrder
from agno.utils.log import log_info


def attach_routes(router: APIRouter, knowledge: Knowledge) -> APIRouter:
    @router.post("/documents")
    async def upload_documents(
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        url: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON string of metadata dict or list of dicts"),
        file: Optional[UploadFile] = File(None),
    ):
        log_info(f"Uploading documents: {name}, {description}, {url}, {metadata}")
        # # Generate ID immediately
        document_id = str(uuid4())
        log_info(f"Document ID: {document_id}")
        # # Read the content once and store it
        if file:
            content_bytes = await file.read()
        else:
            content_bytes = None

        parsed_urls = None
        if url and url.strip():
            try:
                log_info(f"Parsing URL: {url}")
                parsed_urls = json.loads(url)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a single URL string
                parsed_urls = url if url != "string" else None
        log_info(f"Parsed URLs: {parsed_urls}")
        # # Parse metadata with proper error handling
        parsed_metadata = None
        if metadata and metadata.strip():
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None

        document_content = DocumentContent(
            content=content_bytes,
            type=file.content_type if file.content_type else None,
        ) if file else None

        document = DocumentV2(
            name=name if name else file.filename,
            description=description,
            url=parsed_urls,
            metadata=parsed_metadata,
            content=document_content,
            size=file.size if file else None,
        )

        # Add the processing task to background tasks
        background_tasks.add_task(process_document, knowledge, document_id, document)

        # Return immediately with the ID
        return {"document_id": document_id, "status": "processing"}

    @router.get("/documents", response_model=PaginatedResponse[DocumentResponseSchema], status_code=200)
    def get_documents(
        limit: Optional[int] = Query(default=20, description="Number of documents to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[DocumentResponseSchema]:
        documents, count = knowledge.get_documents(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

        return PaginatedResponse(
            data=[
                DocumentResponseSchema(
                    id=document.id,
                    name=document.name,
                    description=document.description,
                    type=document.content.type if document.content else None,
                    size=str(document.size) if document.size else "0",
                    metadata=document.metadata,
                    linked_to=knowledge.name,
                )
                for document in documents
            ],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=count,
                total_pages=math.ceil(count / limit) if limit is not None and limit > 0 else 0,
            ),
        )

    @router.get("/documents/{document_id}", response_model=DocumentResponseSchema, status_code=200)
    def get_document_by_id(document_id: str) -> DocumentResponseSchema:
        log_info(f"Getting document by id: {document_id}")

        document = knowledge.get_document(document_id=document_id)

        document = DocumentResponseSchema(
            id=document_id,
            name=document.name,
            description=document.description,
            type=document.content.type if document.content else None,
            size=str(len(document.content.content)) if document.content else "0",
            linked_to=knowledge.name,
            metadata=document.metadata,
            access_count=0,
        )

        return document

    @router.delete(
        "/documents/{document_id}",
        response_model=DocumentResponseSchema,
        status_code=200,
        response_model_exclude_none=True,
    )
    def delete_document_by_id(document_id: str) -> DocumentResponseSchema:
        knowledge.remove_document(document_id=document_id)
        log_info(f"Deleting document by id: {document_id}")

        return DocumentResponseSchema(
            id=document_id,
        )

    @router.delete("/documents/", status_code=200)
    def delete_all_documents():
        log_info(f"Deleting all documents")
        return "success"

    @router.get("/documents/{document_id}/status")
    async def get_document_status(document_id: str):
        """Get the processing status of a document"""
        try:
            # Try to get the document from the database
            document = knowledge.get_document(document_id)
            return {"document_id": document_id, "status": "completed", "document": document}
        except Exception as e:
            # Document not found or still processing
            return {"document_id": document_id, "status": "processing", "message": "Document is still being processed"}

    return router


def process_document(knowledge: Knowledge, document_id: str, document: DocumentV2):
    """Background task to process the document"""
    print(f"Processing document {document_id}")
    try:
        # Set the document ID
        document.id = document_id
        # Process the document
        knowledge.add_document(document)
        print(f"Document {document_id} processed successfully")
    except Exception as e:
        print(f"Error processing document {document_id}: {e}")
        # You might want to update a status in the database here
