from typing import List

from fastapi import APIRouter

from agno.knowledge.knowledge import Knowledge
from agno.app.agno_api.managers.knowledge.schemas import DocumentRequestSchema, DocumentResponseSchema
from agno.utils.log import log_info
import uuid

def attach_sync_routes(router: APIRouter, knowledge: Knowledge) -> APIRouter:

    @router.post("/documents", response_model=DocumentResponseSchema, status_code=201)
    def add_document(document: DocumentRequestSchema) -> DocumentResponseSchema:
        # knowledge.add_document(
        #     document=Document(
        #         name=document.name,
        #         content=document.content,
        #     )
        # )
        log_info(f"Adding document: {document}")
    

        return DocumentResponseSchema(
            id=str(uuid.uuid4()),
            name="Document 1",
            description="Description 1",
            type="pdf",
            size="100",
            linked_to="Knowledge Base 1",
            metadata={"user_tag": "User 1"},
        )

    @router.get("/documents", response_model=List[DocumentResponseSchema], status_code=200)
    def get_documents() -> List[DocumentResponseSchema]:
        # documents = knowledge.get_all_documents()
        log_info(f"Getting all documents")

        document_1 = DocumentResponseSchema(
            id=str(uuid.uuid4()),
            name="Document 1",
            description="Description 1",
            type="pdf",
            size="200",
            linked_to="Knowledge Base 1",
            metadata={"user_tag": "User 1"},
        )
        document_2 = DocumentResponseSchema(
            id=str(uuid.uuid4()),
            name="Document 2",
            description="Description 2",
            type="pdf",
            size="100",
            linked_to="Knowledge Base 1",
            metadata={"user_tag": "User 2"},
        )
        return [document_1, document_2]

    @router.get("/documents/{document_id}", response_model=DocumentResponseSchema, status_code=200)
    def get_document_by_id(document_id: str) -> DocumentResponseSchema:
        # document = knowledge.get_document_by_id(document_id=document_id)

        log_info(f"Getting document by id: {document_id}")

        document_1 = DocumentResponseSchema(
            id=str(uuid.uuid4()),
            name="Document 1",
            description="Description 1",
            type="pdf",
            size="100",
            linked_to="1",
            metadata={"user_tag": "User 1"},
        )

        return document_1

    @router.delete("/documents/{document_id}", response_model=DocumentResponseSchema, status_code=200)
    def delete_document_by_id(document_id: str) -> DocumentResponseSchema:
        # deleted_document = knowledge.delete_document(document_id=document_id)
        log_info(f"Deleting document by id: {document_id}")

        return DocumentResponseSchema(
            id=str(uuid.uuid4()),
            name="Document 1",
        )

    @router.delete("/documents/", status_code=200)
    def delete_all_documents():
        # knowledge.delete_all_documents()
        log_info(f"Deleting all documents")
        return [
            DocumentResponseSchema(
                id=str(uuid.uuid4()),
                name="Document 1",
            ),
            DocumentResponseSchema(
                id=str(uuid.uuid4()),
                name="Document 2",
            ),
            DocumentResponseSchema(
                id=str(uuid.uuid4()),
                name="Document 3",
            ),
        ]

    return router
