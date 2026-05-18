"""
Schemas for the data-labeling cookbook.

Defines the Pydantic models that flow through the pipeline:
- Invoice            target extraction schema
- LabelResult        a single labeler's output with per-field confidence
- DisagreementReport reviewer's field-by-field diff
- FinalLabel         adjudicated final result
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------
Confidence = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Target extraction schema
# ---------------------------------------------------------------------------
class LineItem(BaseModel):
    description: str = Field(..., description="Item or service description")
    quantity: Optional[float] = Field(None, description="Quantity, if shown")
    unit_price: Optional[float] = Field(None, description="Unit price, if shown")
    total: Optional[float] = Field(None, description="Line total")


class Invoice(BaseModel):
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO yyyy-mm-dd")
    due_date: Optional[str] = Field(None, description="ISO yyyy-mm-dd")
    currency: Optional[str] = Field(None, description="ISO 4217 (USD, EUR, GBP, ...)")
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    line_items: List[LineItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-labeler output
# ---------------------------------------------------------------------------
class FieldConfidence(BaseModel):
    field: str = Field(..., description="Top-level Invoice field name")
    confidence: Confidence
    note: Optional[str] = None


class LabelResult(BaseModel):
    invoice: Invoice
    confidences: List[FieldConfidence] = Field(default_factory=list)
    overall_confidence: Confidence = "medium"


# ---------------------------------------------------------------------------
# Reviewer output
# ---------------------------------------------------------------------------
class FieldDisagreement(BaseModel):
    field: str
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    reason: str = Field(..., description="Why this field needs adjudication")


class DisagreementReport(BaseModel):
    disagreements: List[FieldDisagreement] = Field(default_factory=list)
    any_low_confidence: bool = False
    needs_adjudication: bool = False


# ---------------------------------------------------------------------------
# Adjudicator output
# ---------------------------------------------------------------------------
class AdjudicatedField(BaseModel):
    field: str
    final_value: Optional[str] = None
    rationale: str


class FinalLabel(BaseModel):
    invoice: Invoice
    adjudicated_fields: List[AdjudicatedField] = Field(default_factory=list)
    notes: Optional[str] = None
