from typing import List
from fastapi import APIRouter, Form, File, UploadFile, BackgroundTasks
import json
from uuid import uuid4

from agno.document.document_v2 import DocumentV2, DocumentContent
from agno.os.managers.knowledge.schemas import DocumentResponseSchema
from agno.knowledge.knowledge import Knowledge
from agno.utils.log import log_info
from typing import Optional

from agno.knowledge.knowledge import Knowledge

def attach_routes(router: APIRouter, knowledge: Knowledge) -> APIRouter:
    @router.post("/documents")
    async def upload_documents(
        background_tasks: BackgroundTasks,
        name: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        urls: Optional[str] = Form(None),
        metadata: Optional[str] = Form(None, description="JSON string of metadata dict or list of dicts"),
        file: Optional[UploadFile] = File(None)
    ):
        # Generate ID immediately
        document_id = str(uuid4())
        
        # Read the content once and store it
        content_bytes = await file.read()
        
        parsed_urls = None
        if urls and urls.strip():
            try:
                parsed_urls = json.loads(urls)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a single URL string
                parsed_urls = [urls] if urls != "string" else None

        # Parse metadata with proper error handling
        parsed_metadata = None
        if metadata and metadata.strip():
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as a simple key-value pair
                parsed_metadata = {"value": metadata} if metadata != "string" else None

        document = DocumentV2(
            name=name if name else file.filename,
            description=description,
            urls=parsed_urls,
            metadata=parsed_metadata,
            content=DocumentContent(
                content=content_bytes,
                type=file.content_type
            )
        )
        
        # Add the processing task to background tasks
        background_tasks.add_task(process_document, knowledge, document_id, document)

        # Return immediately with the ID
        return {"document_id": document_id, "status": "processing"}

    @router.get("/documents", response_model=List[DocumentResponseSchema], status_code=200)
    def get_documents() -> List[DocumentResponseSchema]:
        documents = knowledge.get_documents()
        result = []
        for document in documents:
            # Convert DocumentV2 to DocumentResponseSchema
            response_doc = DocumentResponseSchema(
                id=document.id,  # Generate a unique ID
                name=document.name,
                description=document.description,
                type=document.content.type if document.content else None,
                size=str(len(document.content.content)) if document.content else "0",
                linked_to=knowledge.name,
                metadata=document.metadata,
                access_count=0
            )
            result.append(response_doc)
        return result

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
            access_count=0
        )

        return document


    @router.delete("/documents/{document_id}", response_model=DocumentResponseSchema, status_code=200)
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
            return {
                "document_id": document_id,
                "status": "completed",
                "document": document
            }
        except Exception as e:
            # Document not found or still processing
            return {
                "document_id": document_id,
                "status": "processing",
                "message": "Document is still being processed"
            }

    return router

def process_document(knowledge: Knowledge, document_id: str, document: DocumentV2):
    """Background task to process the document"""
    try:
        # Set the document ID
        document.id = document_id
        # Process the document
        knowledge.add_document(document)
        print(f"Document {document_id} processed successfully")
    except Exception as e:
        print(f"Error processing document {document_id}: {e}")
        # You might want to update a status in the database here