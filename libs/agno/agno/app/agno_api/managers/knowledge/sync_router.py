from typing import List

from fastapi import APIRouter

from agno.app.agno_api.managers.knowledge.schemas import DocumentSchema
from agno.knowledge.knowledge_base import Document, KnowledgeBase


def attach_sync_routes(router: APIRouter, knowledge: KnowledgeBase) -> APIRouter:
    @router.post("/documents", response_model=DocumentSchema, status_code=201)
    def add_document(document: DocumentSchema) -> DocumentSchema:
        knowledge.add_document(
            document=Document(
                name=document.name,
                content=document.content,
                # TODO
            )
        )

        return document

    @router.get("/documents", response_model=List[DocumentSchema], status_code=200)
    def get_documents() -> List[DocumentSchema]:
        documents = knowledge.get_all_documents()

        return [
            DocumentSchema(
                name=document.name,
                content=document.content,
                # TODO
            )
            for document in documents
        ]

    @router.get("/documents/{document_id}", response_model=DocumentSchema, status_code=200)
    def get_document_by_id(document_id: str) -> DocumentSchema:
        document = knowledge.get_document_by_id(document_id=document_id)

        return DocumentSchema(
            name=document.name,
            content=document.content,
            # TODO
        )

    @router.delete("/documents/{document_id}", response_model=DocumentSchema, status_code=200)
    def delete_document_by_id(document_id: str) -> DocumentSchema:
        deleted_document = knowledge.delete_document(document_id=document_id)

        return DocumentSchema(
            name=deleted_document.name,
            content=deleted_document.content,
            # TODO
        )

    @router.delete("/documents/", status_code=200)
    def delete_all_documents():
        knowledge.delete_all_documents()

        return

    return router
