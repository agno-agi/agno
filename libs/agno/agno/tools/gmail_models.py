"""
Pydantic models for Gmail API responses and data structures.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GmailLabel(BaseModel):
    """Gmail label information."""

    id: str = Field(..., description="The ID of the label")
    name: Optional[str] = Field(None, description="The display name of the label")
    type: Optional[str] = Field(None, description="The type of label")


class GmailMessageResponse(BaseModel):
    """Gmail Message resource returned by the API."""

    id: str = Field(..., description="The immutable ID of the message")
    threadId: str = Field(..., description="The ID of the thread the message belongs to")
    labelIds: List[str] = Field(default_factory=list, description="List of labels applied to this message")
    snippet: Optional[str] = Field(None, description="A short part of the message text")
    historyId: Optional[str] = Field(None, description="The ID of the last history record that modified this message")
    internalDate: Optional[str] = Field(None, description="The internal message creation timestamp")
    sizeEstimate: Optional[int] = Field(None, description="Estimated size in bytes of the message")
    raw: Optional[str] = Field(
        None, description="The entire email message in an RFC 2822 formatted and base64url encoded string"
    )


class MarkAsReadResponse(BaseModel):
    """Response from marking an email as read."""

    success: bool = Field(..., description="Whether the operation was successful")
    message_id: str = Field(..., description="The ID of the message that was modified")
    message: Optional[GmailMessageResponse] = Field(None, description="The updated message resource from Gmail API")
    error: Optional[str] = Field(None, description="Error message if the operation failed")
    labels_removed: List[str] = Field(default_factory=list, description="List of labels that were removed")

    @classmethod
    def success_response(cls, message_id: str, gmail_response: Dict[str, Any]) -> "MarkAsReadResponse":
        """Create a successful response from Gmail API response."""
        return cls(
            success=True,
            message_id=message_id,
            message=GmailMessageResponse(**gmail_response),
            labels_removed=["UNREAD"],
        )

    @classmethod
    def error_response(cls, message_id: str, error: str) -> "MarkAsReadResponse":
        """Create an error response."""
        return cls(success=False, message_id=message_id, error=error)


class EmailHeader(BaseModel):
    """Email header information."""

    name: str = Field(..., description="Header name")
    value: str = Field(..., description="Header value")


class EmailInfo(BaseModel):
    """Structured email information extracted from Gmail."""

    id: str = Field(..., description="The message ID")
    thread_id: Optional[str] = Field(None, description="The thread ID")
    subject: Optional[str] = Field(None, description="Email subject")
    sender: Optional[str] = Field(None, description="Email sender (From header)")
    date: Optional[str] = Field(None, description="Email date")
    body: Optional[str] = Field(None, description="Email body content")
    in_reply_to: Optional[str] = Field(None, description="In-Reply-To header")
    references: Optional[str] = Field(None, description="References header")
    labels: List[str] = Field(default_factory=list, description="Gmail labels applied to this message")
    is_unread: bool = Field(False, description="Whether the email is unread")

    @classmethod
    def from_gmail_message(cls, gmail_message: Dict[str, Any]) -> "EmailInfo":
        """Create EmailInfo from Gmail API message response."""
        payload = gmail_message.get("payload", {})
        headers = payload.get("headers", [])

        # Extract headers
        header_dict = {h["name"].lower(): h["value"] for h in headers}

        return cls(
            id=gmail_message["id"],
            thread_id=gmail_message.get("threadId"),
            subject=header_dict.get("subject"),
            sender=header_dict.get("from"),
            date=header_dict.get("date"),
            in_reply_to=header_dict.get("in-reply-to"),
            references=header_dict.get("references"),
            labels=gmail_message.get("labelIds", []),
            is_unread="UNREAD" in gmail_message.get("labelIds", []),
        )


class EmailSearchResponse(BaseModel):
    """Response from email search operations."""

    success: bool = Field(..., description="Whether the search was successful")
    total_count: int = Field(0, description="Total number of emails found")
    emails: List[EmailInfo] = Field(default_factory=list, description="List of emails found")
    error: Optional[str] = Field(None, description="Error message if search failed")

    @classmethod
    def success_response(cls, emails: List[EmailInfo]) -> "EmailSearchResponse":
        """Create a successful search response."""
        return cls(success=True, total_count=len(emails), emails=emails)

    @classmethod
    def error_response(cls, error: str) -> "EmailSearchResponse":
        """Create an error response."""
        return cls(success=False, error=error)


class SendEmailResponse(BaseModel):
    """Response from sending an email."""

    success: bool = Field(..., description="Whether the email was sent successfully")
    message_id: Optional[str] = Field(None, description="The ID of the sent message")
    thread_id: Optional[str] = Field(None, description="The thread ID if this was a reply")
    error: Optional[str] = Field(None, description="Error message if sending failed")

    @classmethod
    def success_response(cls, gmail_response: Dict[str, Any]) -> "SendEmailResponse":
        """Create a successful send response from Gmail API response."""
        return cls(success=True, message_id=gmail_response.get("id"), thread_id=gmail_response.get("threadId"))

    @classmethod
    def error_response(cls, error: str) -> "SendEmailResponse":
        """Create an error response."""
        return cls(success=False, error=error)
