"""
Contract Review Schemas
=======================

Pydantic models for structured contract analysis and risk assessment.
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Party Schema
# ============================================================================
class ContractParty(BaseModel):
    """A party to the contract."""

    name: str = Field(description="Name of the party")
    role: str = Field(
        description="Role in contract: buyer, seller, licensor, licensee, employer, employee, landlord, tenant, service_provider, client, other"
    )
    address: Optional[str] = Field(default=None, description="Address if mentioned")
    contact: Optional[str] = Field(
        default=None, description="Contact information if mentioned"
    )


# ============================================================================
# Key Term Schema
# ============================================================================
class KeyTerm(BaseModel):
    """A key term extracted from the contract."""

    term_type: str = Field(
        description="Type: effective_date, expiration_date, renewal_date, amount, payment_terms, notice_period, governing_law, jurisdiction, other"
    )
    value: str = Field(description="The extracted value")
    section: Optional[str] = Field(
        default=None, description="Section or clause where found"
    )
    context: Optional[str] = Field(
        default=None, description="Brief context about this term"
    )


# ============================================================================
# Obligation Schema
# ============================================================================
class Obligation(BaseModel):
    """An obligation or commitment identified in the contract."""

    obligated_party: str = Field(description="Who has this obligation")
    description: str = Field(description="Description of the obligation")
    deadline: Optional[str] = Field(
        default=None, description="Deadline or timeframe if specified"
    )
    section: Optional[str] = Field(default=None, description="Section reference")
    is_recurring: bool = Field(
        default=False, description="Whether this is a recurring obligation"
    )
    priority: str = Field(
        default="medium",
        description="Priority level: high, medium, low based on importance",
    )


# ============================================================================
# Risk Flag Schema
# ============================================================================
class RiskFlag(BaseModel):
    """A potential risk or concern identified in the contract."""

    risk_type: str = Field(
        description="Type: liability_concern, non_standard_clause, missing_protection, ambiguous_language, unfavorable_terms, compliance_risk, termination_risk, ip_risk, confidentiality_risk, indemnification_risk, other"
    )
    severity: str = Field(description="Severity: high, medium, low")
    description: str = Field(description="Description of the risk")
    section: Optional[str] = Field(default=None, description="Section reference")
    recommendation: str = Field(description="Suggested action or mitigation")


# ============================================================================
# Clause Comparison Schema
# ============================================================================
class ClauseComparison(BaseModel):
    """Comparison of a clause against standard templates."""

    clause_type: str = Field(
        description="Type of clause: indemnification, limitation_of_liability, termination, confidentiality, ip_ownership, warranty, dispute_resolution, force_majeure, assignment, amendment, other"
    )
    assessment: str = Field(
        description="Assessment: standard, favorable, unfavorable, missing, non_standard"
    )
    explanation: str = Field(description="Brief explanation of the assessment")
    suggested_revision: Optional[str] = Field(
        default=None, description="Suggested revision if needed"
    )


# ============================================================================
# Redline Suggestion Schema
# ============================================================================
class RedlineSuggestion(BaseModel):
    """A suggested edit or redline to the contract."""

    section: str = Field(description="Section or clause reference")
    original_text: str = Field(description="Original text to be changed")
    suggested_text: str = Field(description="Suggested replacement text")
    rationale: str = Field(description="Reason for the suggested change")
    priority: str = Field(description="Priority: high, medium, low")


# ============================================================================
# Contract Review Result Schema
# ============================================================================
class ContractReview(BaseModel):
    """Complete structured contract review analysis."""

    # Document Info
    contract_type: str = Field(
        description="Type: nda, employment_agreement, service_agreement, vendor_contract, lease, sla, partnership_agreement, licensing_agreement, purchase_agreement, other"
    )
    title: Optional[str] = Field(default=None, description="Contract title if present")

    # Executive Summary
    executive_summary: str = Field(
        description="2-3 paragraph executive summary of the contract and key findings"
    )

    # Parties
    parties: list[ContractParty] = Field(description="Parties to the contract")

    # Key Terms
    key_terms: list[KeyTerm] = Field(description="Key terms extracted from contract")

    # Dates
    effective_date: Optional[date] = Field(
        default=None, description="Contract effective date"
    )
    expiration_date: Optional[date] = Field(
        default=None, description="Contract expiration date"
    )
    renewal_terms: Optional[str] = Field(
        default=None, description="Renewal terms if specified"
    )

    # Financial Terms
    total_value: Optional[str] = Field(
        default=None, description="Total contract value if applicable"
    )
    payment_terms: Optional[str] = Field(
        default=None, description="Payment terms summary"
    )

    # Obligations
    obligations: list[Obligation] = Field(description="Key obligations for each party")

    # Important Deadlines
    key_deadlines: list[str] = Field(
        default_factory=list,
        description="List of important deadlines and dates to track",
    )

    # Risk Analysis
    risk_flags: list[RiskFlag] = Field(description="Identified risks and concerns")
    overall_risk_level: str = Field(
        description="Overall risk assessment: high, medium, low"
    )

    # Clause Analysis
    clause_comparisons: list[ClauseComparison] = Field(
        default_factory=list,
        description="Comparison of key clauses against standard practices",
    )

    # Redline Suggestions
    redline_suggestions: list[RedlineSuggestion] = Field(
        default_factory=list, description="Suggested edits to improve the contract"
    )

    # Additional Notes
    missing_clauses: list[str] = Field(
        default_factory=list,
        description="Standard clauses that are missing from the contract",
    )
    ambiguous_sections: list[str] = Field(
        default_factory=list, description="Sections with ambiguous or unclear language"
    )

    # Metadata
    word_count: int = Field(description="Original document word count")
    confidence: float = Field(
        description="Confidence in analysis accuracy 0-1", ge=0.0, le=1.0
    )
