"""
Strale Compliance Agent
=======================

This cookbook shows how to build a compliance-focused Agno agent using Strale
for KYB checks, sanctions screening, and IBAN validation.

Prerequisites:
- Install the Strale SDK: uv pip install straleio
- Set STRALE_API_KEY for paid capabilities such as KYB and sanctions checks:
  export STRALE_API_KEY="sk_live_..."
- IBAN validation is available in Strale's free tier without an API key.
- Set your model provider key, for example:
  export OPENAI_API_KEY="..."
"""

import json
import os
from typing import Any, Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured Output Schema
# ---------------------------------------------------------------------------


class ComplianceCheck(BaseModel):
    """A single compliance check performed by the agent."""

    check_type: Literal["kyb", "sanctions", "iban"] = Field(
        ..., description="The type of compliance check performed"
    )
    status: Literal["pass", "review", "fail", "unknown"] = Field(
        ..., description="The normalized outcome of the check"
    )
    summary: str = Field(..., description="Short explanation of the result")
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Compliance risks, mismatches, or missing evidence",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Relevant Strale evidence, sources, audit URLs, or transaction IDs",
    )


class ComplianceReport(BaseModel):
    """Decision-ready compliance report for onboarding review."""

    entity_name: str = Field(..., description="Business or person being reviewed")
    recommendation: Literal["approve", "manual_review", "reject"] = Field(
        ..., description="Recommended onboarding decision"
    )
    checks: list[ComplianceCheck] = Field(
        ..., description="KYB, sanctions, and IBAN check results"
    )
    required_follow_ups: list[str] = Field(
        default_factory=list,
        description="Missing documents, checks, or analyst actions required",
    )


# ---------------------------------------------------------------------------
# Strale SDK Helper
# ---------------------------------------------------------------------------


def _get_strale_client():
    try:
        from straleio import Strale
    except ImportError as exc:
        raise RuntimeError(
            "The Strale SDK is required for this cookbook. Install it with "
            "`uv pip install straleio` or `pip install straleio`."
        ) from exc

    return Strale(
        api_key=os.getenv("STRALE_API_KEY", ""),
        default_max_price_cents=int(os.getenv("STRALE_MAX_PRICE_CENTS", "200")),
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]

    payload: dict[str, Any] = {}
    for attr in ("output", "quality", "audit", "status", "capability_used"):
        if hasattr(value, attr):
            payload[attr] = _jsonable(getattr(value, attr))
    return payload or str(value)


def _run_strale(
    *,
    capability_slug: Optional[str] = None,
    inputs: Optional[dict[str, Any]] = None,
    task: Optional[str] = None,
    max_price_cents: int = 200,
) -> str:
    strale = _get_strale_client()
    kwargs: dict[str, Any] = {"max_price_cents": max_price_cents}
    if capability_slug:
        kwargs["capability_slug"] = capability_slug
    if inputs:
        kwargs["inputs"] = inputs
    if task:
        kwargs["task"] = task

    result = strale.do(**kwargs)
    return json.dumps(_jsonable(result), indent=2)


# ---------------------------------------------------------------------------
# Strale Tool Wrappers
# ---------------------------------------------------------------------------


@tool(show_result=True)
def run_kyb_check(
    company_name: str,
    country_code: str,
    registration_number: Optional[str] = None,
) -> str:
    """Run a KYB check for a business using Strale's company and compliance data."""
    task = (
        f"Run a KYB check for {company_name} in {country_code}. "
        "Return company status, registration details, ownership or registry evidence "
        "when available, quality score, and audit trail."
    )
    if registration_number:
        task += f" Registration number: {registration_number}."

    return _run_strale(task=task, max_price_cents=200)


@tool(show_result=True)
def screen_sanctions(name: str, country: Optional[str] = None) -> str:
    """Screen a business or person against sanctions lists using Strale."""
    inputs = {"name": name}
    if country:
        inputs["country"] = country
    return _run_strale(
        capability_slug="sanctions-check",
        inputs=inputs,
        max_price_cents=100,
    )


@tool(show_result=True)
def validate_iban(iban: str) -> str:
    """Validate an IBAN using Strale's free IBAN validation capability."""
    return _run_strale(
        capability_slug="iban-validate",
        inputs={"iban": iban},
        max_price_cents=10,
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


compliance_agent = Agent(
    name="Strale Compliance Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[run_kyb_check, screen_sanctions, validate_iban],
    output_schema=ComplianceReport,
    instructions=[
        "You are a compliance analyst performing onboarding checks.",
        "Use the Strale tools for every KYB, sanctions, and IBAN validation claim.",
        "Do not infer pass/fail status without tool evidence.",
        "Treat missing data, tool errors, or low-quality results as manual_review.",
        "Summarize evidence using audit URLs, transaction IDs, sources, or quality scores when present.",
        "Return a concise decision-ready report using the structured output schema.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    response = compliance_agent.run(
        "Onboard Klarna Bank AB in Sweden. "
        "Run KYB using registration number 556737-0431, screen the company "
        "against sanctions, and validate IBAN DE89370400440532013000. "
        "Give an onboarding recommendation."
    )

    report: ComplianceReport = response.content
    print(json.dumps(report.model_dump(), indent=2))
