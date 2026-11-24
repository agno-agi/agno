"""Opt-in Company configuration."""

from dataclasses import InitVar, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from agno.company.declarations import Goal
from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.base import Model


@dataclass
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
    # The 3.2.0 name of goals.
    products: InitVar[Optional[List["Goal"]]] = None

    def __post_init__(self, products: Optional[List["Goal"]]) -> None:
        from agno.db.schemas.company import validate_company_details

        if products is not None:
            if self.goals:
                raise ValueError("Give goals or products, not both")
            self.goals = products

        validate_company_details({"name": self.name, "description": self.description})
        if (
            isinstance(self.automation_history_retention_days, bool)
            or not isinstance(self.automation_history_retention_days, int)
            or self.automation_history_retention_days < 1
        ):
            raise ValueError("automation_history_retention_days must be a positive integer")
        if not isinstance(self.cron_expr, str) or not self.cron_expr.strip():
            raise ValueError("cron_expr must be a cron expression")
