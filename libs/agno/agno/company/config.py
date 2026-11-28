"""Opt-in Company configuration."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from agno.company.declarations import Goal
from agno.company.filesystem import COMPANY_FILESYSTEM_BYTES
from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.base import Model


@dataclass(init=False)
class CompanyConfig:
    """Company resources. An omitted database inherits AgentOS.db at assembly."""

    db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    model: Optional[Model] = None
    goals: List["Goal"] = field(default_factory=list)
    acceptance_checks: Dict[str, Callable[[Dict[str, Any], Any], Any]] = field(default_factory=dict)
    automation_history_retention_days: int = 30
    cron_expr: str = "0 * * * *"
    name: str = "Company"
    description: Optional[str] = None
    # The size limit of the Company file system: every file under wiki/, goals/, tasks/ and notes/.
    max_filesystem_bytes: int = COMPANY_FILESYSTEM_BYTES

    def __init__(
        self,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        model: Optional[Model] = None,
        goals: Optional[List["Goal"]] = None,
        acceptance_checks: Optional[Dict[str, Callable[[Dict[str, Any], Any], Any]]] = None,
        automation_history_retention_days: int = 30,
        cron_expr: str = "0 * * * *",
        name: str = "Company",
        description: Optional[str] = None,
        products: Optional[List["Goal"]] = None,
        *,
        max_filesystem_bytes: int = COMPANY_FILESYSTEM_BYTES,
    ) -> None:
        # products is the 3.2.0 name of goals. dataclasses.replace(config, products=...) passes the goals
        # of the config it copies along with the new products, so products is used when both are given.
        self.db = db
        self.model = model
        self.goals = products if products is not None else (goals if goals is not None else [])
        self.acceptance_checks = acceptance_checks if acceptance_checks is not None else {}
        self.automation_history_retention_days = automation_history_retention_days
        self.cron_expr = cron_expr
        self.name = name
        self.description = description
        self.max_filesystem_bytes = max_filesystem_bytes
        self.__post_init__()

    @property
    def products(self) -> List["Goal"]:
        """The 3.2.0 name of goals."""
        return self.goals

    @products.setter
    def products(self, value: List["Goal"]) -> None:
        self.goals = value

    def __post_init__(self) -> None:
        from agno.db.schemas.company import validate_company_details

        validate_company_details({"name": self.name, "description": self.description})
        if (
            isinstance(self.automation_history_retention_days, bool)
            or not isinstance(self.automation_history_retention_days, int)
            or self.automation_history_retention_days < 1
        ):
            raise ValueError("automation_history_retention_days must be a positive integer")
        if not isinstance(self.cron_expr, str) or not self.cron_expr.strip():
            raise ValueError("cron_expr must be a cron expression")
        if (
            isinstance(self.max_filesystem_bytes, bool)
            or not isinstance(self.max_filesystem_bytes, int)
            or self.max_filesystem_bytes < 1
        ):
            raise ValueError("max_filesystem_bytes must be a positive integer")
