
from abc import ABC, abstractmethod
from fastapi import APIRouter


class BaseConnector(ABC):

    type: str
    version: str = "1.0"
    router_prefix: str = ""
    connector_id: str = ""

    router: APIRouter

    @abstractmethod
    def get_router(self, **kwargs) -> APIRouter:
        pass
