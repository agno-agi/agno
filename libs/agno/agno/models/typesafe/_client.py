from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from typesafe_sdk import AsyncTypeSafeClient, TypeSafeClient, TypeSafeError

from agno.models.typesafe._schemas import DecisionSchema, json_state


@dataclass
class DecisionResult:
    values: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass
class JevClient:
    model: str = "jev-latest"
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    timeout: Optional[float] = None
    client: Any = field(default=None, repr=False)
    async_client: Any = field(default=None, repr=False)

    def _kwargs(self) -> Dict[str, Any]:
        return {
            k: v
            for k, v in {"api_key": self.api_key, "base_url": self.base_url, "timeout": self.timeout}.items()
            if v is not None
        }

    def get_client(self) -> TypeSafeClient:
        if self.client is None:
            self.client = TypeSafeClient(**self._kwargs())
        return self.client

    def get_async_client(self) -> AsyncTypeSafeClient:
        if self.async_client is None:
            self.async_client = AsyncTypeSafeClient(**self._kwargs())
        return self.async_client

    @staticmethod
    def _result(response: Any, schema: DecisionSchema) -> DecisionResult:
        data = response.model_dump(mode="json")
        try:
            request_id = response.request_id
        except (AttributeError, TypeSafeError):
            request_id = None
        if request_id:
            data["request_id"] = request_id
        return DecisionResult(schema.values(response.answers), data)

    def evaluate(self, state: Any, schema: DecisionSchema) -> DecisionResult:
        response = self.get_client().system_one(json_state(state), schema.questions, model=self.model)
        return self._result(response, schema)

    async def aevaluate(self, state: Any, schema: DecisionSchema) -> DecisionResult:
        response = await self.get_async_client().system_one(json_state(state), schema.questions, model=self.model)
        return self._result(response, schema)
