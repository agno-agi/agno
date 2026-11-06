"""Human-owned Company details, scoped to the configured Company database."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agno.company.execution import _call
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id


class CompanyDetails(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: int
    updated_at: int


class CompanyDetailsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: int = Field(ge=0)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=20000)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("Company name must not be blank")
        return value


def get_company_details_router(agent_os: Any) -> APIRouter:
    router = APIRouter(prefix="/company", tags=["Company"], dependencies=[Depends(get_scoped_user_id)])
    authentication = get_authentication_dependency(agent_os.settings)

    async def read() -> Dict[str, Any]:
        if agent_os._company_db is None:
            raise HTTPException(503, "Company requires a database")
        try:
            # Insert-only lazy initialization also supports applications without lifespan startup.
            return await _call(
                agent_os._company_db, "initialize_company", agent_os.company.name, agent_os.company.description
            )
        except NotImplementedError:
            raise HTTPException(503, "Company details not supported by the configured database")

    @router.get("/details/access")
    async def details_access(request: Request, _: bool = Depends(authentication)) -> Dict[str, bool]:
        from agno.os.authz.run_context import request_authorization

        authority = request_authorization(request)
        try:
            if authority is not None:
                await authority.arequire("agent_os", "admin")
            return {"can_edit": True}
        except PermissionError:
            return {"can_edit": False}

    @router.get("/details", response_model=CompanyDetails)
    async def get_details(_: bool = Depends(authentication)) -> Dict[str, Any]:
        return await read()

    @router.patch("/details", response_model=CompanyDetails)
    async def update_details(body: CompanyDetailsUpdate, _: bool = Depends(authentication)) -> Dict[str, Any]:
        await read()
        result = await _call(
            agent_os._company_db,
            "update_company",
            body.expected_updated_at,
            **body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}),
        )
        if result is None:
            raise HTTPException(409, "Company details changed. Reload before saving your edits.")
        return result

    return router
