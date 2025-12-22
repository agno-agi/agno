"""Memory management MCP tools for AgentOS."""

from typing import TYPE_CHECKING, List, Optional, cast
from uuid import uuid4

from fastmcp import FastMCP

from agno.db.base import AsyncBaseDb
from agno.db.schemas import UserMemory
from agno.os.routers.memory.schemas import UserMemorySchema, UserStatsSchema
from agno.os.utils import get_db

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def register_memory_tools(mcp: FastMCP, os: "AgentOS") -> None:
    """Register memory management MCP tools."""

    @mcp.tool(
        name="create_memory",
        description="Create a new user memory",
        tags={"memory"},
    )  # type: ignore
    async def create_memory(
        db_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        user_memory = db.upsert_user_memory(
            memory=UserMemory(
                memory_id=str(uuid4()),
                memory=memory,
                topics=topics or [],
                user_id=user_id,
            ),
            deserialize=False,
        )
        if not user_memory:
            raise Exception("Failed to create memory")

        return UserMemorySchema.from_dict(user_memory).model_dump()  # type: ignore

    @mcp.tool(
        name="get_memories_for_user",
        description="Get a paginated list of memories for a user with optional filtering",
        tags={"memory"},
    )  # type: ignore
    async def get_memories_for_user(
        user_id: str,
        db_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memories, total_count = await db.get_user_memories(
                limit=limit,
                page=page,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                search_content=search_content,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            user_memories, total_count = db.get_user_memories(  # type: ignore
                limit=limit,
                page=page,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                search_content=search_content,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        return {
            "data": [UserMemorySchema.from_dict(user_memory).model_dump() for user_memory in user_memories],  # type: ignore
            "total_count": total_count,
            "page": page,
            "limit": limit,
        }

    @mcp.tool(
        name="get_memory",
        description="Get a specific memory by ID",
        tags={"memory"},
    )  # type: ignore
    async def get_memory(
        memory_id: str,
        db_id: str,
        user_id: Optional[str] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.get_user_memory(memory_id=memory_id, user_id=user_id, deserialize=False)
        else:
            user_memory = db.get_user_memory(memory_id=memory_id, user_id=user_id, deserialize=False)

        if not user_memory:
            raise Exception(f"Memory with ID {memory_id} not found")

        return UserMemorySchema.from_dict(user_memory).model_dump()  # type: ignore

    @mcp.tool(
        name="update_memory",
        description="Update a memory",
        tags={"memory"},
    )  # type: ignore
    async def update_memory(
        db_id: str,
        memory_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=memory,
                    topics=topics or [],
                    user_id=user_id,
                ),
                deserialize=False,
            )
        else:
            user_memory = db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=memory,
                    topics=topics or [],
                    user_id=user_id,
                ),
                deserialize=False,
            )
        if not user_memory:
            raise Exception("Failed to update memory")

        return UserMemorySchema.from_dict(user_memory).model_dump()  # type: ignore

    @mcp.tool(
        name="delete_memory",
        description="Delete a memory by ID",
        tags={"memory"},
    )  # type: ignore
    async def delete_memory(
        db_id: str,
        memory_id: str,
        user_id: Optional[str] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memory(memory_id=memory_id, user_id=user_id)
        else:
            db.delete_user_memory(memory_id=memory_id, user_id=user_id)

        return {"message": f"Memory {memory_id} deleted successfully"}

    @mcp.tool(
        name="delete_memories",
        description="Delete multiple memories by their IDs",
        tags={"memory"},
    )  # type: ignore
    async def delete_memories(
        memory_ids: List[str],
        db_id: str,
        user_id: Optional[str] = None,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)
        else:
            db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)

        return {"message": f"Deleted {len(memory_ids)} memories"}

    @mcp.tool(
        name="get_memory_topics",
        description="Get all unique topics associated with memories",
        tags={"memory"},
    )  # type: ignore
    async def get_memory_topics(
        db_id: str,
    ) -> List[str]:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            return await db.get_all_memory_topics()
        else:
            return db.get_all_memory_topics()

    @mcp.tool(
        name="get_user_memory_stats",
        description="Get paginated statistics about memory usage by user",
        tags={"memory"},
    )  # type: ignore
    async def get_user_memory_stats(
        db_id: str,
        limit: int = 20,
        page: int = 1,
    ) -> dict:
        db = await get_db(os.dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_stats, total_count = await db.get_user_memory_stats(
                limit=limit,
                page=page,
            )
        else:
            user_stats, total_count = db.get_user_memory_stats(
                limit=limit,
                page=page,
            )
        return {
            "data": [UserStatsSchema.from_dict(stats).model_dump() for stats in user_stats],
            "total_count": total_count,
            "page": page,
            "limit": limit,
        }

    @mcp.tool(
        name="optimize_memories",
        description="Optimize all memories for a user using summarization strategy",
        tags={"memory"},
    )  # type: ignore
    async def optimize_memories(
        user_id: str,
        db_id: str,
        model: Optional[str] = None,
        apply: bool = True,
    ) -> dict:
        from agno.memory import MemoryManager
        from agno.memory.strategies.summarize import SummarizeStrategy
        from agno.memory.strategies.types import MemoryOptimizationStrategyType
        from agno.models.utils import get_model

        db = await get_db(os.dbs, db_id)

        # Create memory manager with optional model
        if model:
            model_instance = get_model(model)
            memory_manager = MemoryManager(model=model_instance, db=db)
        else:
            memory_manager = MemoryManager(db=db)

        # Get current memories to count tokens before optimization
        if isinstance(db, AsyncBaseDb):
            memories_before = await memory_manager.aget_user_memories(user_id=user_id)
        else:
            memories_before = memory_manager.get_user_memories(user_id=user_id)

        if not memories_before:
            raise Exception(f"No memories found for user {user_id}")

        # Count tokens before optimization
        strategy = SummarizeStrategy()
        tokens_before = strategy.count_tokens(memories_before)
        memories_before_count = len(memories_before)

        # Optimize memories with default SUMMARIZE strategy
        if isinstance(db, AsyncBaseDb):
            optimized_memories = await memory_manager.aoptimize_memories(
                user_id=user_id,
                strategy=MemoryOptimizationStrategyType.SUMMARIZE,
                apply=apply,
            )
        else:
            optimized_memories = memory_manager.optimize_memories(
                user_id=user_id,
                strategy=MemoryOptimizationStrategyType.SUMMARIZE,
                apply=apply,
            )

        # Count tokens after optimization
        tokens_after = strategy.count_tokens(optimized_memories)
        memories_after_count = len(optimized_memories)

        # Calculate statistics
        tokens_saved = tokens_before - tokens_after
        reduction_percentage = (tokens_saved / tokens_before * 100.0) if tokens_before > 0 else 0.0

        # Convert to schema objects
        from datetime import datetime

        optimized_memory_schemas = []
        for mem in optimized_memories:
            # Convert epoch timestamp to datetime if needed
            updated_at_dt = None
            if mem.updated_at:
                if isinstance(mem.updated_at, int):
                    updated_at_dt = datetime.fromtimestamp(mem.updated_at)
                else:
                    updated_at_dt = mem.updated_at

            optimized_memory_schemas.append(
                UserMemorySchema(
                    memory_id=mem.memory_id or "",
                    memory=mem.memory or "",
                    topics=mem.topics,
                    agent_id=mem.agent_id,
                    team_id=mem.team_id,
                    user_id=mem.user_id,
                    updated_at=updated_at_dt,
                ).model_dump()
            )

        return {
            "memories": optimized_memory_schemas,
            "memories_before": memories_before_count,
            "memories_after": memories_after_count,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_saved,
            "reduction_percentage": reduction_percentage,
        }
