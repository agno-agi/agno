from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import uuid4

from pydantic import BaseModel

from agno.db.base import BaseDb
from agno.models.base import Model
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.vectordb.base import VectorDb


@dataclass
class Registry:
    """
    Registry is used to manage non serializable objects like tools, models, databases and vector databases.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid4()))
    tools: List[Any] = field(default_factory=list)
    models: List[Model] = field(default_factory=list)
    dbs: List[BaseDb] = field(default_factory=list)
    vector_dbs: List[VectorDb] = field(default_factory=list)
    schemas: List[Type[BaseModel]] = field(default_factory=list)
    functions: List[Callable] = field(default_factory=list)

    @cached_property
    def _entrypoint_lookup(self) -> Dict[str, Callable]:
        lookup: Dict[str, Callable] = {}
        for tool in self.tools:
            if isinstance(tool, Toolkit):
                for func in tool.functions.values():
                    if func.entrypoint is not None:
                        lookup[func.name] = func.entrypoint
            elif isinstance(tool, Function):
                if tool.entrypoint is not None:
                    lookup[tool.name] = tool.entrypoint
            elif callable(tool):
                lookup[tool.__name__] = tool
        return lookup

    def rehydrate_function(self, func_dict: Dict[str, Any]) -> Function:
        """Reconstruct a Function from dict, reattaching its entrypoint."""
        func = Function.from_dict(func_dict)
        func.entrypoint = self._entrypoint_lookup.get(func.name)
        return func

    def get_schema(self, name: str) -> Optional[Type[BaseModel]]:
        """Get a schema by name."""
        if self.schemas:
            return next((s for s in self.schemas if s.__name__ == name), None)
        return None

    def get_db(self, db_id: str) -> Optional[BaseDb]:
        """Get a database by id from the registry.

        Args:
            db_id: The database id to look up

        Returns:
            The database instance if found, None otherwise
        """
        if self.dbs:
            return next((db for db in self.dbs if db.id == db_id), None)
        return None

    def get_function(self, name: str) -> Optional[Callable]:
        return next((f for f in self.functions if f.__name__ == name), None)
