import math
from typing import List, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Path, Query
from fastapi.routing import APIRouter

from agno.db.base import BaseDb
from agno.db.schemas import UserMemory
from agno.os.apps.memory.schemas import (
    DeleteMemoriesRequest,
    UserMemoryCreateSchema,
    UserMemorySchema,
    UserStatsSchema,
)
from agno.os.apps.utils import PaginatedResponse, PaginationInfo, SortOrder


def parse_topics(topics: Optional[List[str]] = Query(default=None)) -> Optional[List[str]]:
    """Parse a comma-separated string of topics into a list of topics"""
    if not topics:
        return None

    try:
        return [topic.strip() for topic in topics[0].split(",") if topic.strip()]

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid topics: {e}")


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.post("/memories", response_model=UserMemorySchema, status_code=200)
    async def create_memory(payload: UserMemoryCreateSchema) -> UserMemorySchema:
        user_memory = db.upsert_user_memory(
            memory=UserMemory(
                memory_id=str(uuid4()),
                memory=payload.memory,
                topics=payload.topics or [],
                user_id=payload.user_id,
            ),
            deserialize=False,
        )
        if not user_memory:
            raise HTTPException(status_code=500, detail="Failed to create memory")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @router.delete("/memories/{memory_id}", status_code=204)
    async def delete_memory(memory_id: str = Path()) -> None:
        db.delete_user_memory(memory_id=memory_id)

    @router.delete("/memories", status_code=204)
    async def delete_memories(request: DeleteMemoriesRequest) -> None:
        db.delete_user_memories(memory_ids=request.memory_ids)

    @router.get("/memories", response_model=PaginatedResponse[UserMemorySchema], status_code=200)
    async def get_memories(
        user_id: Optional[str] = Query(default=None, description="Filter memories by user ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter memories by agent ID"),
        team_id: Optional[str] = Query(default=None, description="Filter memories by team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Filter memories by workflow ID"),
        topics: Optional[List[str]] = Depends(parse_topics),
        search_content: Optional[str] = Query(default=None, description="Fuzzy search memory content"),
        limit: Optional[int] = Query(default=20, description="Number of memories to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="updated_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[UserMemorySchema]:
        user_memories, total_count = db.get_user_memories(
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
            deserialize=False,
        )
        return PaginatedResponse(
            data=[UserMemorySchema.from_dict(user_memory) for user_memory in user_memories],  # type: ignore
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,  # type: ignore
                total_pages=math.ceil(total_count / limit) if limit is not None and limit > 0 else 0,  # type: ignore
            ),
        )

    @router.get("/memories/{memory_id}", response_model=UserMemorySchema, status_code=200)
    async def get_memory(memory_id: str = Path()) -> UserMemorySchema:
        user_memory = db.get_user_memory(memory_id=memory_id, deserialize=False)
        if not user_memory:
            raise HTTPException(status_code=404, detail=f"Memory with ID {memory_id} not found")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @router.get("/topics", response_model=List[str], status_code=200)
    async def get_topics() -> List[str]:
        return db.get_all_memory_topics()

    @router.patch("/memories/{memory_id}", response_model=UserMemorySchema, status_code=200)
    async def update_memory(payload: UserMemoryCreateSchema, memory_id: str = Path()) -> UserMemorySchema:
        user_memory = db.upsert_user_memory(
            memory=UserMemory(
                memory_id=memory_id,
                memory=payload.memory,
                topics=payload.topics or [],
                user_id=payload.user_id,
            ),
            deserialize=False,
        )
        if not user_memory:
            raise HTTPException(status_code=500, detail="Failed to update memory")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @router.get("/users", response_model=PaginatedResponse[UserStatsSchema], status_code=200)
    async def get_user_memory_stats(
        limit: Optional[int] = Query(default=20, description="Number of items to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
    ) -> PaginatedResponse[UserStatsSchema]:
        try:
            user_stats, total_count = db.get_user_memory_stats(
                limit=limit,
                page=page,
            )
            return PaginatedResponse(
                data=[UserStatsSchema.from_dict(stats) for stats in user_stats],
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_count=total_count,
                    total_pages=(total_count + limit - 1) // limit if limit is not None and limit > 0 else 0,
                ),
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get user statistics: {str(e)}")

    return router
