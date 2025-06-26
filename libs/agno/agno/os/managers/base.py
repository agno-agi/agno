from abc import ABC, abstractmethod
from typing import Any, Dict
from fastapi import APIRouter


class BaseManager(ABC):
    type: str
    version: str = "1.0"
    router_prefix: str = ""
    name: str = ""

    router: APIRouter

    @abstractmethod
    def get_router(self, index: int, **kwargs) -> APIRouter:
        pass
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
        }
