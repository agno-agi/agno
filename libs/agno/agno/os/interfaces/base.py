from abc import ABC, abstractmethod

from fastapi import APIRouter


class BaseInterface(ABC):
    type: str
    version: str = "1.0"
    router_prefix: str = ""

    router: APIRouter

    @abstractmethod
    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        pass
