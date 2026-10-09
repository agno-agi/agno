"""Async facade over the optional SQL sandbox registry contract."""

import asyncio
import inspect
from typing import Any, Dict, List, Optional


class _SandboxRegistry:
    def __init__(self, db: Any):
        self.db = db

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self.db, method)
        if inspect.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def get(
        self, *, session_id: Optional[str] = None, sandbox_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        return await self.call("get_sandbox", session_id=session_id, sandbox_id=sandbox_id)

    async def list(self, agent_id: str) -> List[Dict[str, Any]]:
        return await self.call("list_sandboxes", agent_id=agent_id)

    async def insert(self, row: Dict[str, Any]) -> bool:
        return await self.call("upsert_sandbox", row)

    async def replace(self, row: Dict[str, Any], **changes: Any) -> bool:
        return await self.call("upsert_sandbox", {**row, **changes}, row["revision"])
