import json
import time
from os import getenv
from pathlib import Path
from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from mistralai import Mistral
from prompts import get_prompt_for_document_type
from schemas import CommercialInvoice, FedExLabel, PackingList
from textwrap import dedent

# Mistral API key
mistral_api_key = getenv("MISTRAL_API_KEY")
mistral_client = Mistral(api_key=mistral_api_key)

# Data directory
data_dir = Path(__file__).parent / "data/03_882845951760_Medtronic/"


def save_json(response: Dict[str, Any], file_path: Path):
    # Create output JSON filename based on input PDF filename
    output_filename = file_path.stem + "_extracted.json"
    output_path = file_path.parent / output_filename
    
    if response.content:
        extracted_data = response.content.model_dump()
        
        # Write to JSON file
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f, indent=2, ensure_ascii=False)
            
        print(f"✅ Extracted data written to: {output_path}")
        return extracted_data
    else:
        print(f"❌ No structured data extracted from {file_path.name}")
        return None

# Utility functions
def detect_document_type(file_path: Path) -> str:
    """Detect document type from filename."""
    filename = file_path.name.upper()

    if filename.startswith("AWB") or "AWB" in filename:
        return "fedex_label"
    elif filename.startswith("CI") or "COMMERCIAL" in filename or "INVOICE" in filename:
        return "commercial_invoice"
    elif "PACKING" in filename or "PACK" in filename or "PL" in filename:
        return "packing_list"
    else:
        return "unknown"


def get_output_schema(document_type: str):
    """Get appropriate Pydantic schema for document type."""
    schema_mapping = {
        "fedex_label": FedExLabel,
        "commercial_invoice": CommercialInvoice,
        "packing_list": PackingList,
    }
    return schema_mapping.get(document_type)


def get_document_type_and_schema(file_path: Path) -> tuple[str, type]:
    """Detect document type from filename and return both type and schema."""
    document_type = detect_document_type(file_path)
    output_schema = get_output_schema(document_type)
    return document_type, output_schema

agent = Agent(
    model=OpenAIChat(id="gpt-4o", temperature=0),
    instructions=[
        dedent("""
            You are a specialist in extracting structured data from Medtronic logistics documents using Mistral OCR text.
            Clean up OCR artifacts while preserving exact numbers, codes, and identifiers with 100% accuracy.

            🎯 DOCUMENT-SPECIFIC EXTRACTION REQUIREMENTS (Based on actual document analysis):
            FedEx Labels (AWB) - Single Page Documents:
            - PRIMARY GOAL: Extract tracking number after 'TRK#' (CRITICAL for downstream systems)
            - Tracking formats seen: '8829 2284 4080', '8828459517460' - extract complete sequence
            - Weight typically in KG format (e.g., '110.00 KG', '370.00 KG')
            - Dimensions in CM format (e.g., '120 X 100 X 160 CM')
            - Ship from/to addresses include company names and full addresses
            - Customs values with currency codes (NZD, USD, etc.)

            Commercial Invoices - Multi-Page Documents (Pages 2-13 typically):
            - Header: Invoice numbers like '8101017886', dates like '21-Jul-2025'
            - Addresses: Medtronic companies (Australasia to New Zealand typically)
            - LINE ITEMS (MOST CRITICAL): Extract from ALL pages, ALL line items:
            - Material Numbers: Long codes like 'A763000567401' (CRITICAL)
            - Descriptions: Medical devices like 'CATHETER LA6MB1 LA 6F 100CM MB1'
            - Country codes: MX, US, CH, FR, etc.
            - Quantities with UOM: EA, PK, CA, CT
            - Prices: Unit prices and extended prices
            - May contain 50+ line items across multiple pages

            Export Packing Lists (Usually Page 1 of invoice documents):
            - Header: 'EXPORT PACKING LIST SUMMARY'
            - Customer: 'Medtronic New Zealand' typically
            - Packing slip numbers: Long sequences like '1458658698', '1458780549'
            - Measurements: Length, width, height, total cubic volume
            - Weight: Total weight in KGS

            🔧 EXTRACTION RULES (Zero Error Tolerance):
            - Preserve exact formatting of all codes and numbers
            - Extract EVERY line item - missing items cause system failures
            - Fix OCR errors but maintain original number sequences
            - If unsure about a field, mark as null rather than guessing
            - Pay special attention to Material Numbers and Part Numbers (system-critical)
        """),
    ],
)

def extract_data(file_path: Path) -> Optional[Dict[str, Any]]:
    # get document type and schema
    document_type, output_schema = get_document_type_and_schema(file_path)
    # Set the output schema based on the document type
    agent.output_schema = output_schema
    
    # RUN OCR ON PDF
    uploaded_pdf = mistral_client.files.upload( # type: ignore
        file={
            "file_name": file_path.name,
            "content": open(file_path, "rb"),
        },
        purpose="ocr",
    )

    signed_url = mistral_client.files.get_signed_url(file_id=uploaded_pdf.id)
    ocr_response = mistral_client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": signed_url.url,
        },
        include_image_base64=False,
    )

    ocr_text = str(ocr_response).strip()

    # get prompt
    prompt = get_prompt_for_document_type(document_type, ocr_text)

    # run agent
    response = agent.run(prompt)

    # save json
    save_json(response, file_path)

if __name__ == "__main__":
    # get all PDFs
    invoice_files = list(data_dir.glob("*.PDF")) + list(data_dir.glob("*.pdf"))

    for file_path in invoice_files:
        extract_data(file_path)
