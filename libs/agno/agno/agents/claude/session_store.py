"""Claude SDK transcript storage bound to an Agno project."""

import asyncio
from typing import Any, Dict, List, Optional, Union

from agno.db.base import AsyncBaseDb, BaseDb


class AgnoSessionStore:
    """Implement the SDK's async store protocol using a sync or async Agno DB.

    All incoming SDK keys use this store's project_key, including keys derived
    from the SDK working directory during resume.
    """

    def __init__(self, db: Union[BaseDb, AsyncBaseDb], project_key: str):
        self.db = db
        self.project_key = project_key

    async def _call(self, method: str, **kwargs: Any) -> Any:
        fn = getattr(self.db, method)
        if isinstance(self.db, AsyncBaseDb):
            return await fn(project_key=self.project_key, **kwargs)
        return await asyncio.to_thread(fn, project_key=self.project_key, **kwargs)

    async def append(self, key: Dict[str, Any], entries: List[Dict[str, Any]]) -> None:
        await self._call(
            "append_transcript_entries", session_id=key["session_id"], subpath=key.get("subpath"), entries=entries
        )

    async def load(self, key: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        entries = await self._call("get_transcript_entries", session_id=key["session_id"], subpath=key.get("subpath"))
        return entries or None

    async def list_sessions(self, project_key: str) -> List[Dict[str, Any]]:
        return await self._call("list_transcript_sessions")

    async def list_subkeys(self, key: Dict[str, Any]) -> List[str]:
        return await self._call("list_transcript_subpaths", session_id=key["session_id"])

    async def delete(self, key: Dict[str, Any]) -> None:
        await self._call("delete_transcript", session_id=key["session_id"], subpath=key.get("subpath"))
