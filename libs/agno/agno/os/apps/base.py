from abc import ABC, abstractmethod
from typing import Optional

from fastapi import APIRouter

from agno.os.settings import AgnoAPISettings


class BaseApp(ABC):
    type: str
    version: str = "1.0"
    router_prefix: str = ""
    display_name: Optional[str] = None

    router: APIRouter

    @abstractmethod
    def get_router(self, index: int, settings: AgnoAPISettings, **kwargs) -> APIRouter:
        pass
