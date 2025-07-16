from abc import ABC, abstractmethod

from fastapi import APIRouter


class BaseApp(ABC):
    type: str
    version: str = "1.0"
    router_prefix: str = ""
    name: str = ""

    router: APIRouter

    @abstractmethod
    def get_router(self, index: int, **kwargs) -> APIRouter:
        pass
