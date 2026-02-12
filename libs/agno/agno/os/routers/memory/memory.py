import logging
import math
from typing import List, Optional, Union, cast
from uuid import uuid4

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas import UserMemory
from agno.models.utils import get_model
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.routers.memory.schemas import (
    DeleteMemoriesRequest,
    OptimizeMemoriesRequest,
    OptimizeMemoriesResponse,
    UserMemoryCreateSchema,
    UserMemorySchema,
    UserStatsSchema,
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
from agno.os.utils import get_db
from agno.remote.base import RemoteDb

logger = logging.getLogger(__name__)


def get_memory_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
) -> APIRouter:
    """Create memory router with comprehensive OpenAPI documentation for user memory management endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Memory"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> APIRouter:
    @router.post(
        "/memories",
        response_model=UserMemorySchema,
        status_code=200,
        operation_id="create_memory",
        summary="Create Memory",
        description=(
            "Create a new user memory with content and associated topics. "
            "Memories are used to store contextual information for users across conversations."
        ),
        responses={
            200: {
                "description": "Memory created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "memory_id": "mem-123",
                            "memory": "User prefers technical explanations with code examples",
                            "topics": ["preferences", "communication_style", "technical"],
                            "user_id": "user-456",
                            "created_at": "2024-01-15T10:30:00Z",
                            "updated_at": "2024-01-15T10:30:00Z",
                        }
                    }
                },
            },
            400: {"description": "Invalid request data", "model": BadRequestResponse},
            422: {"description": "Validation error in payload", "model": ValidationErrorResponse},
            500: {"description": "Failed to create memory", "model": InternalServerErrorResponse},
        },
    )
    async def create_memory(
        request: Request,
        payload: UserMemoryCreateSchema,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for memory storage"),
        table: Optional[str] = Query(default=None, description="Table to use for memory storage"),
    ) -> UserMemorySchema:
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id
            payload.user_id = user_id

        if payload.user_id is None:
            raise HTTPException(status_code=400, detail="User ID is required")

        db = await get_db(dbs, db_id, table)

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.create_memory(
                memory=payload.memory,
                topics=payload.topics or [],
                user_id=payload.user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=str(uuid4()),
                    memory=payload.memory,
                    topics=payload.topics or [],
                    user_id=payload.user_id,
                ),
                deserialize=False,
            )
        else:
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

    @router.delete(
        "/memories/{memory_id}",
        status_code=204,
        operation_id="delete_memory",
        summary="Delete Memory",
        description="Permanently delete a specific user memory. This action cannot be undone.",
        responses={
            204: {"description": "Memory deleted successfully"},
            404: {"description": "Memory not found", "model": NotFoundResponse},
            500: {"description": "Failed to delete memory", "model": InternalServerErrorResponse},
        },
    )
    async def delete_memory(
        request: Request,
        memory_id: str = Path(description="Memory ID to delete"),
        user_id: Optional[str] = Query(default=None, description="User ID to delete memory for"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
        table: Optional[str] = Query(default=None, description="Table to use for deletion"),
    ) -> None:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.delete_memory(
                memory_id=memory_id,
                user_id=user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memory(memory_id=memory_id, user_id=user_id)
        else:
            db.delete_user_memory(memory_id=memory_id, user_id=user_id)

    @router.delete(
        "/memories",
        status_code=204,
        operation_id="delete_memories",
        summary="Delete Multiple Memories",
        description=(
            "Delete multiple user memories by their IDs in a single operation. "
            "This action cannot be undone and all specified memories will be permanently removed."
        ),
        responses={
            204: {"description": "Memories deleted successfully"},
            400: {"description": "Invalid request - empty memory_ids list", "model": BadRequestResponse},
            500: {"description": "Failed to delete memories", "model": InternalServerErrorResponse},
        },
    )
    async def delete_memories(
        http_request: Request,
        request: DeleteMemoriesRequest,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
        table: Optional[str] = Query(default=None, description="Table to use for deletion"),
    ) -> None:
        db = await get_db(dbs, db_id, table)

        if hasattr(http_request.state, "user_id") and http_request.state.user_id is not None:
            request.user_id = http_request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(http_request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.delete_memories(
                memory_ids=request.memory_ids,
                user_id=request.user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_user_memories(memory_ids=request.memory_ids, user_id=request.user_id)
        else:
            db.delete_user_memories(memory_ids=request.memory_ids, user_id=request.user_id)

    @router.get(
        "/memories",
        response_model=PaginatedResponse[UserMemorySchema],
        status_code=200,
        operation_id="get_memories",
        summary="List Memories",
        description=(
            "Retrieve paginated list of user memories with filtering and search capabilities. "
            "Filter by user, agent, team, topics, or search within memory content."
        ),
        responses={
            200: {
                "description": "Memories retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "memory_id": "f9361a69-2997-40c7-ae4e-a5861d434047",
                                    "memory": "User likes coffee.",
                                    "topics": ["preferences"],
                                    "agent_id": None,
                                    "team_id": None,
                                    "user_id": "123",
                                    "updated_at": "2025-09-01T07:53:17Z",
                                }
                            ]
                        }
                    }
                },
            }
        },
    )
    async def get_memories(
        request: Request,
        user_id: Optional[str] = Query(default=None, description="Filter memories by user ID"),
        agent_id: Optional[str] = Query(default=None, description="Filter memories by agent ID"),
        team_id: Optional[str] = Query(default=None, description="Filter memories by team ID"),
        topics: Optional[List[str]] = Depends(parse_topics),
        search_content: Optional[str] = Query(default=None, description="Fuzzy search within memory content"),
        limit: Optional[int] = Query(default=20, description="Number of memories to return per page", ge=1),
        page: Optional[int] = Query(default=1, description="Page number for pagination", ge=0),
        sort_by: Optional[str] = Query(default="updated_at", description="Field to sort memories by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query memories from"),
        table: Optional[str] = Query(default=None, description="The database table to use"),
    ) -> PaginatedResponse[UserMemorySchema]:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_memories(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                topics=topics,
                search_content=search_content,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order.value if sort_order else "desc",
                db_id=db_id,
                table=table,
                headers=headers,
            )

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

        memories = [UserMemorySchema.from_dict(user_memory) for user_memory in user_memories]  # type: ignore
        return PaginatedResponse(
            data=[memory for memory in memories if memory is not None],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,  # type: ignore
                total_pages=math.ceil(total_count / limit) if limit is not None and limit > 0 else 0,  # type: ignore
            ),
        )

    @router.get(
        "/memories/{memory_id}",
        response_model=UserMemorySchema,
        status_code=200,
        operation_id="get_memory",
        summary="Get Memory by ID",
        description="Retrieve detailed information about a specific user memory by its ID.",
        responses={
            200: {
                "description": "Memory retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "memory_id": "f9361a69-2997-40c7-ae4e-a5861d434047",
                            "memory": "User likes coffee.",
                            "topics": ["preferences"],
                            "agent_id": None,
                            "team_id": None,
                            "user_id": "123",
                            "updated_at": "2025-09-01T07:53:17Z",
                        }
                    }
                },
            },
            404: {"description": "Memory not found", "model": NotFoundResponse},
        },
    )
    async def get_memory(
        request: Request,
        memory_id: str = Path(description="Memory ID to retrieve"),
        user_id: Optional[str] = Query(default=None, description="User ID to query memory for"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query memory from"),
        table: Optional[str] = Query(default=None, description="Table to query memory from"),
    ) -> UserMemorySchema:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_memory(
                memory_id=memory_id,
                user_id=user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.get_user_memory(memory_id=memory_id, user_id=user_id, deserialize=False)
        else:
            user_memory = db.get_user_memory(memory_id=memory_id, user_id=user_id, deserialize=False)
        if not user_memory:
            raise HTTPException(status_code=404, detail=f"Memory with ID {memory_id} not found")

        return UserMemorySchema.from_dict(user_memory)  # type: ignore

    @router.get(
        "/memory_topics",
        response_model=List[str],
        status_code=200,
        operation_id="get_memory_topics",
        summary="Get Memory Topics",
        description=(
            "Retrieve all unique topics associated with memories in the system. "
            "Useful for filtering and categorizing memories by topic."
        ),
        responses={
            200: {
                "description": "Memory topics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            "preferences",
                            "communication_style",
                            "technical",
                            "industry",
                            "compliance",
                            "code_examples",
                            "requirements",
                            "healthcare",
                            "finance",
                        ]
                    }
                },
            }
        },
    )
    async def get_topics(
        request: Request,
        user_id: Optional[str] = Query(default=None, description="User ID to filter topics for"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query topics from"),
        table: Optional[str] = Query(default=None, description="Table to query topics from"),
    ) -> List[str]:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_memory_topics(
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            return await db.get_all_memory_topics(user_id=user_id)
        else:
            return db.get_all_memory_topics(user_id=user_id)

    @router.patch(
        "/memories/{memory_id}",
        response_model=UserMemorySchema,
        status_code=200,
        operation_id="update_memory",
        summary="Update Memory",
        description=(
            "Update an existing user memory's content and topics. "
            "Replaces the entire memory content and topic list with the provided values."
        ),
        responses={
            200: {
                "description": "Memory updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "memory_id": "f9361a69-2997-40c7-ae4e-a5861d434047",
                            "memory": "User likes coffee.",
                            "topics": ["preferences"],
                            "agent_id": None,
                            "team_id": None,
                            "user_id": "123",
                            "updated_at": "2025-09-01T07:53:17Z",
                        }
                    }
                },
            },
            400: {"description": "Invalid request data", "model": BadRequestResponse},
            404: {"description": "Memory not found", "model": NotFoundResponse},
            422: {"description": "Validation error in payload", "model": ValidationErrorResponse},
            500: {"description": "Failed to update memory", "model": InternalServerErrorResponse},
        },
    )
    async def update_memory(
        request: Request,
        payload: UserMemoryCreateSchema,
        memory_id: str = Path(description="Memory ID to update"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for update"),
        table: Optional[str] = Query(default=None, description="Table to use for update"),
    ) -> UserMemorySchema:
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id
            payload.user_id = user_id

        if payload.user_id is None:
            raise HTTPException(status_code=400, detail="User ID is required")

        db = await get_db(dbs, db_id, table)

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.update_memory(
                memory_id=memory_id,
                user_id=payload.user_id,
                memory=payload.memory,
                topics=payload.topics or [],
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            user_memory = await db.upsert_user_memory(
                memory=UserMemory(
                    memory_id=memory_id,
                    memory=payload.memory,
                    topics=payload.topics or [],
                    user_id=payload.user_id,
                ),
                deserialize=False,
            )
        else:
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

    @router.get(
        "/user_memory_stats",
        response_model=PaginatedResponse[UserStatsSchema],
        status_code=200,
        operation_id="get_user_memory_stats",
        summary="Get User Memory Statistics",
        description=(
            "Retrieve paginated statistics about memory usage by user. "
            "Provides insights into user engagement and memory distribution across users."
        ),
        responses={
            200: {
                "description": "User memory statistics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "user_id": "123",
                                    "total_memories": 3,
                                    "last_memory_updated_at": "2025-09-01T07:53:17Z",
                                }
                            ]
                        }
                    }
                },
            },
            500: {"description": "Failed to retrieve user statistics", "model": InternalServerErrorResponse},
        },
    )
    async def get_user_memory_stats(
        request: Request,
        limit: Optional[int] = Query(default=20, description="Number of user statistics to return per page", ge=1),
        page: Optional[int] = Query(default=1, description="Page number for pagination", ge=0),
        user_id: Optional[str] = Query(default=None, description="User ID to filter statistics for"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query statistics from"),
        table: Optional[str] = Query(default=None, description="Table to query statistics from"),
    ) -> PaginatedResponse[UserStatsSchema]:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_user_memory_stats(
                limit=limit,
                page=page,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        try:
            # Ensure limit and page are integers
            limit = int(limit) if limit is not None else 20
            page = int(page) if page is not None else 1
            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                user_stats, total_count = await db.get_user_memory_stats(
                    limit=limit,
                    page=page,
                    user_id=user_id,
                )
            else:
                user_stats, total_count = db.get_user_memory_stats(
                    limit=limit,
                    page=page,
                    user_id=user_id,
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

    @router.post(
        "/optimize-memories",
        response_model=OptimizeMemoriesResponse,
        status_code=200,
        operation_id="optimize_memories",
        summary="Optimize User Memories",
        description=(
            "Optimize all memories for a given user using the default summarize strategy. "
            "This operation combines all memories into a single comprehensive summary, "
            "achieving maximum token reduction while preserving all key information. "
            "To use a custom model, specify the model parameter in 'provider:model_id' format "
            "(e.g., 'openai:gpt-4o-mini', 'anthropic:claude-3-5-sonnet-20241022'). "
            "If not specified, uses MemoryManager's default model (gpt-4o). "
            "Set apply=false to preview optimization results without saving to database."
        ),
        responses={
            200: {
                "description": "Memories optimized successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "memories": [
                                {
                                    "memory_id": "f9361a69-2997-40c7-ae4e-a5861d434047",
                                    "memory": "User has a 3-year-old golden retriever named Max who loves fetch and walks. Lives in San Francisco's Mission district, works as a product manager in tech. Enjoys hiking Bay Area trails, trying new restaurants (especially Japanese, Thai, Mexican), and learning piano for 1.5 years.",
                                    "topics": ["pets", "location", "work", "hobbies", "food_preferences"],
                                    "user_id": "user2",
                                    "updated_at": "2025-11-18T10:30:00Z",
                                }
                            ],
                            "memories_before": 4,
                            "memories_after": 1,
                            "tokens_before": 450,
                            "tokens_after": 180,
                            "tokens_saved": 270,
                            "reduction_percentage": 60.0,
                        }
                    }
                },
            },
            400: {
                "description": "Bad request - User ID is required or invalid model string format",
                "model": BadRequestResponse,
            },
            404: {"description": "No memories found for user", "model": NotFoundResponse},
            500: {"description": "Failed to optimize memories", "model": InternalServerErrorResponse},
        },
    )
    async def optimize_memories(
        http_request: Request,
        request: OptimizeMemoriesRequest,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for optimization"),
        table: Optional[str] = Query(default=None, description="Table to use for optimization"),
    ) -> OptimizeMemoriesResponse:
        """Optimize user memories using the default summarize strategy."""
        from agno.memory import MemoryManager
        from agno.memory.strategies.types import MemoryOptimizationStrategyType

        if hasattr(http_request.state, "user_id") and http_request.state.user_id is not None:
            request.user_id = http_request.state.user_id

        try:
            # Get database instance
            db = await get_db(dbs, db_id, table)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(http_request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.optimize_memories(
                    user_id=request.user_id,
                    model=request.model,
                    apply=request.apply,
                    db_id=db_id,
                    table=table,
                    headers=headers,
                )

            # Create memory manager with optional model
            if request.model:
                try:
                    model_instance = get_model(request.model)
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                memory_manager = MemoryManager(model=model_instance, db=db)
            else:
                # No model specified - use MemoryManager's default
                memory_manager = MemoryManager(db=db)

            # Get current memories to count tokens before optimization
            if isinstance(db, AsyncBaseDb):
                memories_before = await memory_manager.aget_user_memories(user_id=request.user_id)
            else:
                memories_before = memory_manager.get_user_memories(user_id=request.user_id)

            if not memories_before:
                raise HTTPException(status_code=404, detail=f"No memories found for user {request.user_id}")

            # Count tokens before optimization
            from agno.memory.strategies.summarize import SummarizeStrategy

            strategy = SummarizeStrategy()
            tokens_before = strategy.count_tokens(memories_before)
            memories_before_count = len(memories_before)

            # Optimize memories with default SUMMARIZE strategy
            if isinstance(db, AsyncBaseDb):
                optimized_memories = await memory_manager.aoptimize_memories(
                    user_id=request.user_id,
                    strategy=MemoryOptimizationStrategyType.SUMMARIZE,
                    apply=request.apply,
                )
            else:
                optimized_memories = memory_manager.optimize_memories(
                    user_id=request.user_id,
                    strategy=MemoryOptimizationStrategyType.SUMMARIZE,
                    apply=request.apply,
                )

            # Count tokens after optimization
            tokens_after = strategy.count_tokens(optimized_memories)
            memories_after_count = len(optimized_memories)

            # Calculate statistics
            tokens_saved = tokens_before - tokens_after
            reduction_percentage = (tokens_saved / tokens_before * 100.0) if tokens_before > 0 else 0.0

            # Convert to schema objects
            optimized_memory_schemas = [
                UserMemorySchema(
                    memory_id=mem.memory_id or "",
                    memory=mem.memory or "",
                    topics=mem.topics,
                    agent_id=mem.agent_id,
                    team_id=mem.team_id,
                    user_id=mem.user_id,
                    updated_at=mem.updated_at,
                )
                for mem in optimized_memories
            ]

            return OptimizeMemoriesResponse(
                memories=optimized_memory_schemas,
                memories_before=memories_before_count,
                memories_after=memories_after_count,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                tokens_saved=tokens_saved,
                reduction_percentage=reduction_percentage,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to optimize memories for user {request.user_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to optimize memories: {str(e)}")

    return router


def parse_topics(
    topics: Optional[List[str]] = Query(
        default=None,
        description="Comma-separated list of topics to filter by",
        examples=["preferences,technical,communication_style"],
    ),
) -> Optional[List[str]]:
    """Parse comma-separated topics into a list for filtering memories by topic."""
    if not topics:
        return None

    try:
        return [topic.strip() for topic in topics[0].split(",") if topic.strip()]

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid topics format: {e}")
