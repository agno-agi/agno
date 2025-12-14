from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict

from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.base import Model
from agno.tools.toolkit import Toolkit


class BuilderConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    tools: Optional[List[Toolkit]] = None
    models: Optional[List[Model]] = None
    databases: Optional[List[Union[BaseDb, AsyncBaseDb]]] = None
