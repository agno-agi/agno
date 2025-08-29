def get_fedex_label_prompt(ocr_text: str) -> str:
    return f"""
        You are a specialist in extracting structured data from documents. The input is extracted text from a document.

        🎯 CRITICAL: For FedEx Labels, the tracking number is the MOST IMPORTANT field for downstream systems.

        TRACKING NUMBER EXTRACTION (TOP PRIORITY):
        - Look for 'TRK#' followed by a number sequence
        - The tracking number can be in various formats:
          * "8829 2284 4080" (space-separated)
          * "8828459517460" (continuous)
          * May have different spacing patterns
        - Extract the complete number sequence after TRK#

        ADDITIONAL SHIPPING DETAILS:
        - Ship From: Complete sender address including company name, street, city, country
        - Ship To: Complete recipient address including company name, street, city, country  
        - Actual Weight: Weight in KG (look for weight measurements)
        - Dimensions: Package dimensions in CM (format like "120 X 100 X 160 CM")
        - Customs Value: Declared customs value and currency
        - Booking Number: Any booking reference numbers
        - Description: Description of goods being shipped

        MISTRAL OCR TEXT:
        {ocr_text}

        Extract all fields with maximum accuracy. The tracking number is CRITICAL - double-check this extraction.
    """


def get_commercial_invoice_prompt(ocr_text: str) -> str:
    return f"""
Convert this Mistral OCR text from a into structured data.

🎯 CRITICAL REQUIREMENTS - Extract BOTH header data AND every single line item:

HEADER-LEVEL EXTRACTION (Required):
- Invoice Number: Look for invoice number (like "8101017886")
- Invoice Date: Date in format like "21-Jul-2025"  
- Delivery From: Sender company and complete address
- Delivery To: Recipient company and complete address

LINE-LEVEL EXTRACTION (MOST CRITICAL - Extract EVERY line item):
This invoice contains multiple line items across many pages. For EACH line item, extract:

CRITICAL FIELDS (Must capture accurately):
- Material Number: Long alphanumeric codes like "A763000567401" (CRITICAL for system integration)
- CFN Product Number: Product codes that appear with Material Number
- Part Number: Specific part identifiers (CRITICAL field as specified by user)

REQUIRED DETAILS FOR EACH ITEM:
- Item Description: Full product description (e.g., "CATHETER LA6MB1 LA 6F 100CM MB1")
- Country of Origin: 2-letter country codes (MX, US, CH, FR, etc.)
- Quantity: Numeric quantity ordered
- Unit of Measure: UOM codes (EA, PK, CA, CT, etc.)
- Unit Price: Price per individual unit
- Extended Price: Total line price (quantity × unit price)

EXTRACTION INSTRUCTIONS:
- Process ALL pages of the invoice (this may be a multi-page document)
- Extract EVERY line item - do not skip any rows
- Pay special attention to Material Numbers and Part Numbers (critical for downstream systems)
- Maintain exact formatting of codes and part numbers
- If multiple pages, ensure all line items from all pages are captured
- Look for table structures with columns for these data points

MISTRAL OCR TEXT:
{ocr_text}

Extract EVERY line item completely. Missing line items will cause downstream system failures.
"""


def get_packing_list_prompt(ocr_text: str) -> str:
    return f"""
Convert this Mistral OCR text from a into structured data.

🎯 PACKING LIST EXTRACTION - All details needed for downstream processing:

HEADER INFORMATION:
- Packing List Number: Document identifier  
- Date Packed: When items were packed
- Customer: Customer company name and details
- Shipper: Shipping company/method information

PACKAGING DETAILS (Critical for logistics):
- Unit Measurements: Length, width, height dimensions
- Total Cubic: Volume measurements  
- Gross Weight: Total weight in KGS
- Total Weight: Overall shipment weight
- Unit of Packaging: Type of packaging used (pallets, boxes, etc.)

PACKING SLIP NUMBERS (Important for tracking):
- Extract ALL packing slip numbers (these are reference numbers for individual packages)
- Numbers typically in format like "1458658698", "1458780549" etc.
- These numbers link to specific packages in the shipment

ITEM-LEVEL DETAILS:
- Item descriptions and quantities packed
- Package assignments (which items in which packages)
- Any special markings or handling instructions
- Reference numbers linking to invoices or orders

MISTRAL OCR TEXT:
{ocr_text}

Extract all packing details completely - this data is reused in downstream logistics processes.
"""


def get_prompt_for_document_type(
    document_type: str, ocr_text: str
) -> str:

    if document_type == "fedex_label":
        return get_fedex_label_prompt(ocr_text)
    elif document_type == "commercial_invoice":
        return get_commercial_invoice_prompt(ocr_text)
    else:  # packing_list or unknown
        return get_packing_list_prompt(ocr_text)
