"""
Invoice Analyst Schemas
=======================

Pydantic models for structured invoice data extraction.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Address Schema
# ============================================================================
class Address(BaseModel):
    """A postal address."""

    street: Optional[str] = Field(default=None, description="Street address")
    city: Optional[str] = Field(default=None, description="City")
    state: Optional[str] = Field(default=None, description="State/Province")
    postal_code: Optional[str] = Field(default=None, description="ZIP/Postal code")
    country: Optional[str] = Field(default=None, description="Country")


# ============================================================================
# Vendor Schema
# ============================================================================
class Vendor(BaseModel):
    """Vendor/Supplier information."""

    name: str = Field(description="Vendor/Supplier name")
    address: Optional[Address] = Field(default=None, description="Vendor address")
    tax_id: Optional[str] = Field(default=None, description="Tax ID / VAT number")
    email: Optional[str] = Field(default=None, description="Contact email")
    phone: Optional[str] = Field(default=None, description="Contact phone")


# ============================================================================
# Line Item Schema
# ============================================================================
class LineItem(BaseModel):
    """A line item on the invoice."""

    line_number: Optional[int] = Field(default=None, description="Line item number")
    description: str = Field(description="Item description")
    quantity: Optional[float] = Field(default=None, description="Quantity ordered")
    unit: Optional[str] = Field(default=None, description="Unit of measure")
    unit_price: Optional[Decimal] = Field(default=None, description="Price per unit")
    amount: Decimal = Field(description="Line total amount")
    tax_rate: Optional[float] = Field(default=None, description="Tax rate if shown")


# ============================================================================
# Invoice Data Schema
# ============================================================================
class InvoiceData(BaseModel):
    """Complete structured invoice data."""

    # Document Info
    invoice_number: str = Field(description="Invoice number/ID")
    invoice_date: date = Field(description="Invoice issue date")
    due_date: Optional[date] = Field(default=None, description="Payment due date")
    po_number: Optional[str] = Field(
        default=None, description="Purchase order reference"
    )

    # Parties
    vendor: Vendor = Field(description="Vendor information")
    bill_to: Optional[Address] = Field(default=None, description="Billing address")
    ship_to: Optional[Address] = Field(default=None, description="Shipping address")

    # Line Items
    line_items: list[LineItem] = Field(description="Invoice line items")

    # Totals
    subtotal: Decimal = Field(description="Subtotal before tax")
    tax_amount: Optional[Decimal] = Field(default=None, description="Total tax amount")
    tax_rate: Optional[float] = Field(default=None, description="Tax rate percentage")
    discount_amount: Optional[Decimal] = Field(
        default=None, description="Discount applied"
    )
    shipping_amount: Optional[Decimal] = Field(
        default=None, description="Shipping charges"
    )
    total_amount: Decimal = Field(description="Grand total")
    currency: str = Field(default="USD", description="Currency code (USD, EUR, etc.)")

    # Payment
    payment_terms: Optional[str] = Field(
        default=None, description="Payment terms (Net 30, etc.)"
    )
    bank_details: Optional[str] = Field(
        default=None, description="Bank account for payment"
    )

    # Metadata
    confidence_score: float = Field(
        description="Overall extraction confidence 0-1", ge=0.0, le=1.0
    )
    warnings: list[str] = Field(
        default_factory=list, description="Data quality warnings"
    )
