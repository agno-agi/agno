from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

from agno.storage.session import Session


class MessageHistoryStoreDb(ABC):
    """Base class for Message History Store Database"""

    @abstractmethod
    def upsert(self, session: Session) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, user_id: str, session_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self, query: str, limit: int = 5, user_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # @abstractmethod
    # def delete_messages_for_user(self, user_id: str) -> None:
    #     raise NotImplementedError

    # @abstractmethod
    # def delete_messages_for_session(self, session_id: str) -> None:
    #     raise NotImplementedError

    # @abstractmethod
    # def delete_messages_for_user_and_session(self, user_id: str, session_id: str) -> None:
    #     raise NotImplementedError

    # @abstractmethod
    # def delete(self) -> None:
    #     raise NotImplementedError

    # @abstractmethod
    # def exists(self) -> bool:
    #     raise NotImplementedError
