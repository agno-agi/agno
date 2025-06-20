
from abc import ABC, abstractmethod
from fastapi import APIRouter


class BaseManager(ABC):
    
    type: str

    router: APIRouter

    @abstractmethod
    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        pass
