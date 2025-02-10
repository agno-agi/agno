from abc import ABC, abstractmethod
from typing import List, Optional

from agno.storage.workflow.session import WorkflowSession


class WorkflowStorage(ABC):
    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[WorkflowSession]:
        raise NotImplementedError

    @abstractmethod
    def get_all_session_ids(self, user_id: Optional[str] = None, workflow_id: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def get_all_sessions(
        self, user_id: Optional[str] = None, workflow_id: Optional[str] = None
    ) -> List[WorkflowSession]:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, session: WorkflowSession) -> Optional[WorkflowSession]:
        raise NotImplementedError

    @abstractmethod
    def delete_session(self, session_id: Optional[str] = None):
        raise NotImplementedError

    @abstractmethod
    def drop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def upgrade_schema(self) -> None:
        raise NotImplementedError
