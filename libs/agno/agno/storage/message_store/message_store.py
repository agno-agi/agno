from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.models.message import Message
from agno.storage.base import Storage
from agno.storage.message_store.db.base import MessageHistoryStoreDb
from agno.utils.log import log_error


@dataclass
class MessageStore:
    user_id: str
    session_id: str
    messages: Optional[List[Message]] = None
    storage: Optional[Storage] = None
    message_store_db: Optional[MessageHistoryStoreDb] = None

    def load(self):
        """Load messages into the message store"""

        if self.storage is None:
            log_error("Storage is needed to populate message store")
            return

        runs = self.storage.read(session_id=self.session_id, user_id=self.user_id).memory.get("runs", [])
        if runs is None or len(runs) == 0:
            return

        if not self.message_store_db.exists():
            self.message_store_db.create()

        self.message_store_db.upsert(user_id=self.user_id, session_id=self.session_id, runs=runs)

    def read(self):
        """Read messages from the message store"""

        if self.message_store_db is None:
            log_error("Message store db is not set")
            return

        return self.message_store_db.read(session_id=self.session_id, user_id=self.user_id)

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform a vector similarity search over user messages.

        Args:
            query (str): The user query.
            limit (int): The maximum number of results to return.

        Returns:
            List[Dict[str, Any]]: A list of message records.
        """
        results = self.message_store_db.search(
            query=query, user_id=self.user_id, session_id=self.session_id, limit=limit
        )

        if not results:
            return []

        messages: List = []
        for result in results:
            run_messages = result.get("run_messages", [])
            for run_message in run_messages:
                messages.append(
                    Message(
                        role=run_message.get("role"),
                        content=run_message.get("content"),
                    )
                )

        return messages
