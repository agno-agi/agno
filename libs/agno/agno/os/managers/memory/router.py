import math
from typing import List, Optional

from fastapi import HTTPException, Path, Query
from fastapi.routing import APIRouter

from agno.db.schemas import MemoryRow
from agno.memory import Memory
from agno.os.managers.memory.schemas import (
    DeleteMemoriesRequest,
    UserMemoryCreateSchema,
    UserMemorySchema,
    UserStatsSchema,
)
from agno.os.managers.utils import PaginatedResponse, PaginationInfo, SortOrder


def attach_routes(router: APIRouter, memory: Memory) -> APIRouter:
    @router.post("/memories", response_model=UserMemorySchema, status_code=200)
    async def create_memory(payload: UserMemoryCreateSchema) -> UserMemorySchema:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        user_memory = memory.db.upsert_user_memory_raw(
            memory=MemoryRow(
                id=None, memory={"memory": payload.memory, "topics": payload.topics}, user_id=payload.user_id
            )
        )
        if not user_memory:
            raise HTTPException(status_code=500, detail="Failed to create memory")

        return UserMemorySchema.from_dict(user_memory)

    @router.delete("/memories", status_code=204)
    async def delete_memories(request: DeleteMemoriesRequest) -> None:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        memory.db.delete_user_memories(memory_ids=request.memory_ids)

    @router.get("/memories", response_model=PaginatedResponse[UserMemorySchema], status_code=200)
    async def get_memories(
        user_id: Optional[str] = Query(default=None, description="Filter memories by user ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter memories by agent ID"),
        team_id: Optional[str] = Query(default=None, description="Filter memories by team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Filter memories by workflow ID"),
        topics: Optional[List[str]] = Query(default=None, description="Filter memories by topics"),
        search_content: Optional[str] = Query(default=None, description="Fuzzy search memory content"),
        limit: Optional[int] = Query(default=20, description="Number of memories to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="last_updated", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[UserMemorySchema]:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        user_memories, total_count = memory.db.get_user_memories_raw(
            limit=limit,
            page=page,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            topics=topics,
            search_content=search_content,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return PaginatedResponse(
            data=[UserMemorySchema.from_dict(user_memory) for user_memory in user_memories],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,
                total_pages=math.ceil(total_count / limit) if limit is not None and limit > 0 else 0,
            ),
        )

    @router.get("/memories/{memory_id}", response_model=UserMemorySchema, status_code=200)
    async def get_memory(memory_id: str = Path()) -> UserMemorySchema:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        user_memory = memory.db.get_user_memory_raw(memory_id=memory_id)
        if not user_memory:
            raise HTTPException(status_code=404, detail=f"Memory with ID {memory_id} not found")

        return UserMemorySchema.from_dict(user_memory)

    @router.get("/topics", response_model=List[str], status_code=200)
    async def get_topics() -> List[str]:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        return memory.db.get_all_memory_topics()

    @router.patch("/memories/{memory_id}", response_model=UserMemorySchema, status_code=200)
    async def update_memory(payload: UserMemoryCreateSchema, memory_id: str = Path()) -> UserMemorySchema:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        user_memory = memory.db.upsert_user_memory_raw(
            memory=MemoryRow(
                id=memory_id, memory={"memory": payload.memory, "topics": payload.topics or []}, user_id=payload.user_id
            )
        )
        if not user_memory:
            raise HTTPException(status_code=500, detail="Failed to update memory")

        return UserMemorySchema.from_dict(user_memory)

    @router.get("/users", response_model=PaginatedResponse[UserStatsSchema], status_code=200)
    async def get_user_memory_stats(
        limit: Optional[int] = Query(default=20, description="Number of items to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
    ) -> PaginatedResponse[UserStatsSchema]:
        if memory.db is None:
            raise HTTPException(status_code=500, detail="Database not initialized")

        try:
            user_stats, total_count = memory.db.get_user_memory_stats(
                limit=limit,
                page=page,
            )

            return PaginatedResponse(
                data=[UserStatsSchema.from_dict(stats) for stats in user_stats],
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_count=total_count,
                    total_pages=math.ceil(total_count / limit) if limit is not None and limit > 0 else 0,
                ),
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get user statistics: {str(e)}")

    return router
