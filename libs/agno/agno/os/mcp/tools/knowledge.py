"""Knowledge MCP tools for managing content in the knowledge base."""

import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastmcp import FastMCP

from agno.os.utils import get_knowledge_instance_by_db_id
from agno.remote.base import RemoteKnowledge

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_knowledge_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register knowledge management MCP tools."""

    @mcp.tool(
        name="upload_content",
        description="Upload content to the knowledge base. Supports text content or URLs. For file uploads, use the REST API.",
        tags={"knowledge"},
    )  # type: ignore
    async def upload_content(
        db_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        text_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
        chunker: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> dict:
        from agno.knowledge.content import Content, FileData
        from agno.knowledge.reader import ReaderFactory
        from agno.utils.log import log_debug, log_info
        from agno.utils.string import generate_id

        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.upload_content(
                name=name,
                description=description,
                url=url,
                text_content=text_content,
                metadata=metadata,
                reader_id=reader_id,
                chunker=chunker,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                db_id=db_id,
            )
            return result.model_dump()

        log_info(f"Adding content: {name}, {description}, {url}")

        # Parse URL if it's a JSON array
        parsed_urls = None
        if url and url.strip():
            try:
                parsed_urls = json.loads(url)
            except json.JSONDecodeError:
                parsed_urls = url

        # Prepare file data for text content
        if text_content:
            file_data = FileData(
                content=text_content.encode("utf-8"),
                type="manual",
            )
        else:
            file_data = None

        # Auto-generate name if not provided
        if not name:
            if url:
                name = parsed_urls
            elif text_content:
                name = "Text content"

        content = Content(
            name=name,
            description=description,
            url=parsed_urls,
            metadata=metadata,
            file_data=file_data,
        )
        content_hash = knowledge._build_content_hash(content)
        content.content_hash = content_hash
        content.id = generate_id(content_hash)

        # Set reader if specified
        if reader_id:
            reader = None
            custom_readers = knowledge.get_readers()
            if custom_readers and reader_id in custom_readers:
                reader = custom_readers[reader_id]
                log_debug(f"Found custom reader: {reader.__class__.__name__}")
            else:
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

        # Set chunker if specified
        if chunker and content.reader:
            content.reader.set_chunking_strategy_from_string(chunker, chunk_size=chunk_size, overlap=chunk_overlap)
            log_debug(f"Set chunking strategy: {chunker}")

        # Process content
        try:
            await knowledge._load_content_async(content, upsert=False, skip_if_exists=True)
            log_info(f"Content {content.id} processed successfully")
        except Exception as e:
            log_info(f"Error processing content: {e}")
            from agno.knowledge.content import ContentStatus as KnowledgeContentStatus

            content.status = KnowledgeContentStatus.FAILED
            content.status_message = str(e)
            knowledge.patch_content(content)

        return {
            "id": content.id,
            "name": name,
            "description": description,
            "metadata": metadata,
            "status": content.status.value
            if content.status and hasattr(content.status, "value")
            else str(content.status),
            "status_message": content.status_message,
        }

    @mcp.tool(
        name="update_content",
        description="Update content properties like name, description, or metadata",
        tags={"knowledge"},
    )  # type: ignore
    async def update_content(
        content_id: str,
        db_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
    ) -> dict:
        from agno.knowledge.content import Content

        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.update_content(
                content_id=content_id,
                name=name,
                description=description,
                metadata=metadata,
                reader_id=reader_id,
                db_id=db_id,
            )
            return result.model_dump()

        content = Content(
            id=content_id,
            name=name if name and name.strip() else None,
            description=description if description and description.strip() else None,
            metadata=metadata,
        )

        if reader_id and reader_id.strip():
            if knowledge.readers and reader_id in knowledge.readers:
                content.reader = knowledge.readers[reader_id]
            else:
                raise Exception(f"Invalid reader_id: {reader_id}")

        updated_content_dict = knowledge.patch_content(content)
        if not updated_content_dict:
            raise Exception(f"Content not found: {content_id}")

        return {
            "id": updated_content_dict.get("id", content_id),
            "name": updated_content_dict.get("name"),
            "description": updated_content_dict.get("description"),
            "file_type": updated_content_dict.get("file_type"),
            "size": updated_content_dict.get("size"),
            "metadata": updated_content_dict.get("metadata"),
            "status": updated_content_dict.get("status"),
            "status_message": updated_content_dict.get("status_message"),
            "created_at": str(updated_content_dict.get("created_at"))
            if updated_content_dict.get("created_at")
            else None,
            "updated_at": str(updated_content_dict.get("updated_at"))
            if updated_content_dict.get("updated_at")
            else None,
        }

    @mcp.tool(
        name="get_content",
        description="Get a paginated list of all content in the knowledge base",
        tags={"knowledge"},
    )  # type: ignore
    async def get_content(
        db_id: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict:
        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.get_content(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                db_id=db_id,
            )
            return {
                "data": [c.model_dump() for c in result.data],
                "total_count": result.meta.total_count if result.meta else 0,
                "page": page,
                "limit": limit,
            }

        contents, count = await knowledge.aget_content(limit=limit, page=page, sort_by=sort_by, sort_order=sort_order)

        return {
            "data": [
                {
                    "id": content.id,
                    "name": content.name,
                    "description": content.description,
                    "file_type": content.file_type,
                    "size": content.size,
                    "status": content.status.value
                    if content.status and hasattr(content.status, "value")
                    else content.status,
                    "created_at": str(content.created_at) if content.created_at else None,
                    "updated_at": str(content.updated_at) if content.updated_at else None,
                }
                for content in contents
            ],
            "total_count": count,
            "page": page,
            "limit": limit,
        }

    @mcp.tool(
        name="get_content_by_id",
        description="Get detailed information about a specific content item by ID",
        tags={"knowledge"},
    )  # type: ignore
    async def get_content_by_id(content_id: str, db_id: Optional[str] = None) -> dict:
        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)
        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.get_content_by_id(content_id=content_id, db_id=db_id)
            return result.model_dump()

        content = await knowledge.aget_content_by_id(content_id=content_id)
        if not content:
            raise Exception(f"Content {content_id} not found")

        return {
            "id": content_id,
            "name": content.name,
            "description": content.description,
            "file_type": content.file_type,
            "size": len(content.file_data.content) if content.file_data and content.file_data.content else 0,
            "status": content.status.value if content.status and hasattr(content.status, "value") else content.status,
            "status_message": content.status_message,
            "created_at": str(content.created_at) if content.created_at else None,
            "updated_at": str(content.updated_at) if content.updated_at else None,
        }

    @mcp.tool(
        name="get_content_status",
        description="Get the processing status of a content item",
        tags={"knowledge"},
    )  # type: ignore
    async def get_content_status(content_id: str, db_id: Optional[str] = None) -> dict:
        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.get_content_status(content_id=content_id, db_id=db_id)
            return result.model_dump()

        status, status_message = await knowledge.aget_content_status(content_id=content_id)

        if status is None:
            return {"status": "failed", "status_message": status_message or "Content not found"}

        status_value = status.value if hasattr(status, "value") else str(status)
        return {"status": status_value, "status_message": status_message or ""}

    @mcp.tool(
        name="delete_content_by_id",
        description="Delete a specific content item from the knowledge base",
        tags={"knowledge"},
    )  # type: ignore
    async def delete_content_by_id(content_id: str, db_id: Optional[str] = None) -> dict:
        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        # Handle RemoteKnowledge - use remote API
        if isinstance(knowledge, RemoteKnowledge):
            await knowledge.delete_content_by_id(content_id=content_id, db_id=db_id)
            return {"message": f"Content {content_id} deleted successfully"}

        await knowledge.aremove_content_by_id(content_id=content_id)
        return {"message": f"Content {content_id} deleted successfully"}

    @mcp.tool(
        name="delete_all_content",
        description="Delete all content from the knowledge base (use with caution)",
        tags={"knowledge"},
    )  # type: ignore
    async def delete_all_content(db_id: Optional[str] = None) -> dict:
        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            await knowledge.delete_all_content(db_id=db_id)
            return {"message": "All content deleted successfully"}

        knowledge.remove_all_content()
        return {"message": "All content deleted successfully"}

    @mcp.tool(
        name="search_knowledge",
        description="Search the knowledge base for relevant documents",
        tags={"knowledge"},
    )  # type: ignore
    async def search_knowledge(
        query: str,
        db_id: Optional[str] = None,
        max_results: Optional[int] = None,
        filters: Optional[dict] = None,
        search_type: Optional[str] = None,
    ) -> dict:
        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.search_knowledge(
                query=query,
                max_results=max_results,
                filters=filters,
                search_type=search_type,
                db_id=db_id,
            )
            return {
                "data": [r.model_dump() for r in result.data],
                "total_count": result.meta.total_count if result.meta else len(result.data),
            }

        results = knowledge.search(query=query, max_results=max_results, filters=filters, search_type=search_type)

        return {
            "data": [
                {
                    "id": doc.id,
                    "content": doc.content,
                    "name": doc.name,
                    "meta_data": doc.meta_data,
                }
                for doc in results
            ],
            "total_count": len(results),
        }

    @mcp.tool(
        name="get_knowledge_config",
        description="Get available readers, chunkers, and configuration options for content processing",
        tags={"knowledge"},
    )  # type: ignore
    async def get_knowledge_config(db_id: Optional[str] = None) -> dict:
        from agno.knowledge.utils import (
            get_all_chunkers_info,
            get_all_readers_info,
            get_content_types_to_readers_mapping,
        )

        knowledge = get_knowledge_instance_by_db_id(os.knowledge_instances, db_id)

        if isinstance(knowledge, RemoteKnowledge):
            result = await knowledge.get_config()
            return result.model_dump()

        readers_info = get_all_readers_info(knowledge)
        readers = {
            r["id"]: {
                "id": r["id"],
                "name": r["name"],
                "description": r.get("description"),
                "chunkers": r.get("chunking_strategies", []),
            }
            for r in readers_info
        }

        chunkers_list = get_all_chunkers_info()
        chunkers = {
            c["key"]: {
                "key": c["key"],
                "name": c.get("name"),
                "description": c.get("description"),
                "metadata": c.get("metadata", {}),
            }
            for c in chunkers_list
            if c.get("key")
        }

        types_mapping = get_content_types_to_readers_mapping(knowledge)

        vector_dbs = []
        if knowledge.vector_db:
            vector_dbs.append(
                {
                    "id": knowledge.vector_db.id,
                    "name": knowledge.vector_db.name,
                    "description": knowledge.vector_db.description,
                    "search_types": knowledge.vector_db.get_supported_search_types(),
                }
            )

        return {
            "readers": readers,
            "chunkers": chunkers,
            "readersForType": types_mapping,
            "vector_dbs": vector_dbs,
            "filters": knowledge.get_valid_filters(),
        }
