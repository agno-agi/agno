from abc import ABC, abstractmethod
from typing import List, Optional

from agno.memory_v2.db.schema import SummaryRow


class SummaryDb(ABC):
    """Base class for the Memory Database."""

    @abstractmethod
    def create(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def summary_exists(self, summary: SummaryRow) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read_summaries(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[SummaryRow]:
        raise NotImplementedError

    @abstractmethod
    def upsert_summary(self, summary: SummaryRow) -> Optional[SummaryRow]:
        raise NotImplementedError

    @abstractmethod
    def delete_summary(self, session_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def drop_table(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def table_exists(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> bool:
        raise NotImplementedError
