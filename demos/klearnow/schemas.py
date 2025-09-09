"""Comprehensive Pydantic schemas for PDF document extraction"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

# ==================== FEDEX LABEL / AWB SCHEMAS ====================


class FedExLabel(BaseModel):
    """Schema for FedEx shipping label (AWB) extraction."""

    # Key requirement: tracking number
    tracking_number: str = Field(
        ...,
        description="The FedEx tracking number - typically a 12-digit number found near 'TRK#'",
    )

    # Additional shipping information
    origin_id: Optional[str] = Field(None, description="Origin ID from shipping label")

    ship_from: Optional[str] = Field(
        None, description="Complete shipping origin address"
    )

    ship_to: Optional[str] = Field(
        None, description="Complete shipping destination address"
    )

    ship_date: Optional[str] = Field(
        None, description="Shipping date in format found on label"
    )

    actual_weight: Optional[float] = Field(None, description="Actual weight in KG")

    total_weight: Optional[float] = Field(None, description="Total weight in KG")

    dimensions: Optional[str] = Field(
        None, description="Package dimensions (e.g., '120 X 100 X 85 CM')"
    )

    booking_number: Optional[str] = Field(None, description="Booking reference number")

    reference_numbers: Optional[List[str]] = Field(
        None, description="All reference numbers found on the label"
    )

    customs_value: Optional[float] = Field(None, description="Customs value amount")

    customs_currency: Optional[str] = Field(
        None, description="Customs value currency (e.g., 'NZD', 'USD')"
    )

    description: Optional[str] = Field(
        None, description="Description of goods (e.g., 'Medical devices')"
    )


# ==================== COMMERCIAL INVOICE SCHEMAS ====================


class InvoiceItem(BaseModel):
    """Schema for individual line items in commercial invoices."""

    # Key requirements from user
    material_number: Optional[str] = Field(
        None, description="The Material Number - critical field for identification"
    )

    cfn_product_number: Optional[str] = Field(
        None, description="CFN Product Number found in first box with Material Number"
    )

    part_number: str = Field(
        ..., description="The part number - critical field mentioned by user"
    )

    item_description: str = Field(
        ..., description="Full description of the item/product"
    )

    country_of_origin: str = Field(
        ..., description="Country where the item was manufactured/originated"
    )

    quantity: int = Field(..., description="Quantity of items")

    unit_of_measure: str = Field(
        ..., description="Unit of measure (UOM) - e.g., 'EA', 'KG', 'LB'"
    )

    unit_price: float = Field(..., description="Price per unit")

    extended_price: float = Field(
        ..., description="Total price (quantity × unit price)"
    )

    # Additional fields that might be useful
    line_number: Optional[int] = Field(None, description="Line number on the invoice")

    hs_code: Optional[str] = Field(
        None, description="Harmonized System (HS) code for customs classification"
    )

    duty_rate: Optional[float] = Field(None, description="Duty rate if specified")

    net_weight: Optional[float] = Field(None, description="Net weight of the item")

    gross_weight: Optional[float] = Field(None, description="Gross weight of the item")


class CommercialInvoice(BaseModel):
    """Schema for commercial invoice header and line-level data."""

    # Header-level invoice data (user requirements)
    invoice_number: str = Field(..., description="The invoice number from the header")

    invoice_date: str = Field(
        ..., description="Invoice date - typically in MM/DD/YYYY format"
    )

    delivery_from: str = Field(
        ..., description="Complete 'Delivery From' address from invoice header"
    )

    delivery_to: str = Field(
        ..., description="Complete 'Delivery To' address from invoice header"
    )

    # Line-level details (user requirements)
    items: List[InvoiceItem] = Field(
        ..., description="All line items from the commercial invoice"
    )

    # Additional header fields that might be present
    shipper: Optional[str] = Field(None, description="Shipper company/address")

    consignee: Optional[str] = Field(None, description="Consignee company/address")

    currency: Optional[str] = Field(
        None, description="Invoice currency (e.g., 'USD', 'NZD')"
    )

    total_amount: Optional[float] = Field(None, description="Total invoice amount")

    terms_of_sale: Optional[str] = Field(
        None, description="Terms of sale (e.g., 'FOB', 'CIF', 'EXW')"
    )

    payment_terms: Optional[str] = Field(None, description="Payment terms")

    purchase_order: Optional[str] = Field(None, description="Purchase order number")

    export_license: Optional[str] = Field(
        None, description="Export license number if applicable"
    )


# ==================== PACKING LIST SCHEMAS ====================


class PackingItem(BaseModel):
    """Schema for individual items in packing list."""

    item_number: Optional[str] = Field(None, description="Item number or part number")

    description: str = Field(..., description="Description of the packed item")

    quantity: int = Field(..., description="Quantity of items packed")

    unit_of_measure: Optional[str] = Field(None, description="Unit of measure")

    net_weight: Optional[float] = Field(
        None, description="Net weight per item or total"
    )

    gross_weight: Optional[float] = Field(
        None, description="Gross weight per item or total"
    )

    dimensions: Optional[str] = Field(None, description="Item dimensions if specified")

    package_number: Optional[str] = Field(
        None, description="Package or carton number containing this item"
    )

    lot_number: Optional[str] = Field(None, description="Lot or batch number")

    serial_number: Optional[str] = Field(
        None, description="Serial number if applicable"
    )


class PackingList(BaseModel):
    """Schema for packing list extraction - captures all relevant details."""

    # Header information
    packing_list_number: Optional[str] = Field(
        None, description="Packing list document number"
    )

    date: Optional[str] = Field(None, description="Packing list date")

    shipper: Optional[str] = Field(None, description="Shipper information")

    consignee: Optional[str] = Field(None, description="Consignee information")

    # Package/shipment details
    total_packages: Optional[int] = Field(None, description="Total number of packages")

    total_net_weight: Optional[float] = Field(None, description="Total net weight")

    total_gross_weight: Optional[float] = Field(None, description="Total gross weight")

    weight_unit: Optional[str] = Field(
        None, description="Weight unit (e.g., 'KG', 'LB')"
    )

    # Items packed
    items: List[PackingItem] = Field(
        ..., description="All items listed in the packing list"
    )

    # Reference information
    invoice_reference: Optional[str] = Field(None, description="Related invoice number")

    purchase_order: Optional[str] = Field(None, description="Purchase order reference")

    shipping_marks: Optional[str] = Field(None, description="Shipping marks or labels")

    special_instructions: Optional[str] = Field(
        None, description="Any special handling instructions"
    )


# ==================== EXTRACTION RESULT SCHEMAS ====================


class DocumentExtractionResult(BaseModel):
    """Generic result schema for document extraction."""

    file_path: str = Field(..., description="Path to the processed PDF file")

    document_type: str = Field(
        ...,
        description="Type of document: 'fedex_label', 'commercial_invoice', 'packing_list'",
    )

    extraction_method: str = Field(
        ..., description="Method used: 'text_extraction' or 'vision_processing'"
    )

    success: bool = Field(..., description="Whether extraction was successful")

    confidence_score: Optional[float] = Field(
        None, description="Confidence score for the extraction (0.0 to 1.0)"
    )

    processing_time: Optional[float] = Field(
        None, description="Time taken to process the document in seconds"
    )

    extracted_data: Optional[dict] = Field(
        None, description="The extracted structured data"
    )

    raw_text: Optional[str] = Field(
        None, description="Raw text extracted from the document"
    )

    errors: Optional[List[str]] = Field(
        None, description="Any errors encountered during extraction"
    )

    warnings: Optional[List[str]] = Field(
        None, description="Any warnings or issues noted during extraction"
    )
