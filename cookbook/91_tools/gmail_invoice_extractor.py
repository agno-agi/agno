"""
Gmail Invoice Extractor
=======================
Searches for invoices and receipts, extracts structured financial data.

The agent uses search_emails to find invoice-related emails, get_message
to read full content, and the LLM to extract vendor, amount, date, and
category into a structured report.

Setup: See gmail_tools.py for Google OAuth credential setup.
Run: pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools
from pydantic import BaseModel, Field


class Invoice(BaseModel):
    message_id: str = Field(..., description="Gmail message ID")
    vendor: str = Field(..., description="Company or person who sent the invoice")
    amount: str = Field(..., description="Total amount with currency, e.g. '$150.00'")
    date: str = Field(..., description="Invoice or receipt date in YYYY-MM-DD format")
    category: str = Field(
        ..., description="Spending category, e.g. 'Software', 'Travel', 'Office'"
    )
    description: str = Field(..., description="Brief description of what was purchased")
    has_attachment: bool = Field(
        default=False, description="Whether the email has a PDF/image attachment"
    )


class InvoiceReport(BaseModel):
    total_found: int = Field(..., description="Total number of invoices found")
    total_amount: str = Field(..., description="Sum of all invoice amounts")
    invoices: List[Invoice] = Field(
        default_factory=list, description="Extracted invoice details"
    )


agent = Agent(
    name="Invoice Extractor",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(get_message=True)],
    instructions=[
        "Extract: vendor name, total amount (with currency), date, spending category, and description.",
        "If the amount is not explicitly stated, note 'amount not found' rather than guessing.",
        "Categorize spending into: Software, Travel, Office, Subscriptions, Food, or Other.",
        "Calculate the total amount across all invoices found.",
    ],
    output_schema=InvoiceReport,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Find all invoices and receipts from the last 30 days and extract the financial details",
        stream=True,
    )

    # Search for a specific vendor
    # agent.print_response(
    #     "Find all invoices from AWS in the last 3 months",
    #     stream=True,
    # )
