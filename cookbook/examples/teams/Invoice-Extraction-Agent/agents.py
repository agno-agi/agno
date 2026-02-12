import os

from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.google import Gemini

# Load API key from .env and validate
load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise RuntimeError("GOOGLE_API_KEY is not set. Add it to your .env file.")

# 1) Document Parser - produce clean, line-broken text and section hints from PDF
parser_agent = Agent(
    id="parser-agent",
    name="Invoice Document Parser",
    role="Extract all visible text from invoice PDFs in reading order",
    model=Gemini(id="gemini-2.0-flash"),
    instructions="""Extract all text visible in the PDF exactly as written. Preserve reading order (top-to-bottom, left-to-right).

    Rules:
    - Extract only visible text
    - Mark unreadable sections as [UNREADABLE]
    - Mark missing fields as [NOT FOUND]
    - Add section markers if structure is clear: [HEADER], [VENDOR], [BILL_TO], [ITEMS], [TOTALS], [FOOTER]
    - Keep numbers, dates, amounts exactly as written

    Return only the extracted text. No interpretation, no filling gaps.""",
    use_json_mode=False,
    markdown=False,
    send_media_to_model=True, # send the media directly to the model to parse the text
)

# 2) Field Extractor - take transcript and return strict JSON fields
field_extractor_agent = Agent(
    id="extractor-agent",
    name="Invoice Field Extractor",
    role="Extract invoice fields from text into structured JSON",
    model=Gemini(id="gemini-2.0-flash"),
    instructions="""Extract invoice fields from the transcript. Use null for missing values. Do not guess or invent.

    Fields:
    - invoice_number: string or null
    - issue_date: string or null
    - vendor_name: string or null
    - billing_name: string or null
    - currency: string or null
    - subtotal: number or null
    - tax_amount: number or null
    - total_amount: number or null
    - line_items: array of {description, quantity, unit_price, total} or null
    - notes: string or null

    Rules:
    - Extract only what's explicitly stated
    - Mark [UNREADABLE] or [NOT FOUND] as null
    - Convert amounts to numbers (remove currency symbols)
    - Return JSON only.""",
    use_json_mode=True,
    markdown=False,
)

# 3) Validator - check and normalize the extracted JSON
validator_agent = Agent(
    id="validator-agent",
    name="Invoice Validator",
    role="Validate and normalize extracted invoice JSON",
    model=Gemini(id="gemini-2.0-flash"),
    instructions="""Validate and normalize the JSON:
    - Ensure numeric fields are numbers (subtotal, tax_amount, total_amount, line_items quantities/prices)
    - If totals don't match, keep nulls and add note in 'notes' field
    - Do not add fields that weren't present
    - Return corrected JSON with same structure""",
    use_json_mode=True,
    markdown=False,
)


