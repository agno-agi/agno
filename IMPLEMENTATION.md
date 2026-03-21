# Microsoft Graph Connector - Implementation Guide

## Quick Reference for Implementation

This guide provides code examples and patterns for implementing the Microsoft Graph connector for Agno.

---

## 1. Base Toolkit Implementation

### 1.1 Main Toolkit Class

```python
# libs/agno/agno/tools/microsoft_graph/toolkit.py

import json
from os import getenv
from typing import Any, Dict, List, Optional, Union, Literal
from pydantic import BaseModel, Field, validator

from agno.tools import Toolkit
from agno.utils.log import logger

# Authentication
from .auth.manager import GraphAuthenticationManager
from .auth.credentials import build_credential

# Tools
from .tools.mail import GraphMailTools
from .tools.calendar import GraphCalendarTools
from .tools.teams import GraphTeamsTools
from .tools.drive import GraphDriveTools


class GraphConfig(BaseModel):
    """Configuration for Microsoft Graph connector."""

    # Required
    client_id: str = Field(..., description="Entra ID application (client) ID")
    tenant_id: str = Field(..., description="Azure AD tenant ID")

    # Authentication
    auth_mode: Literal["delegated", "app_only"] = Field(
        default="delegated",
        description="Authentication mode: delegated (user) or app_only (service)"
    )
    client_secret: Optional[str] = Field(
        default=None,
        description="Client secret for app-only authentication"
    )
    redirect_uri: Optional[str] = Field(
        default="http://localhost:5000/callback",
        description="OAuth redirect URI for delegated authentication"
    )
    certificate_path: Optional[str] = Field(
        default=None,
        description="Path to certificate for certificate-based authentication"
    )

    # Scopes
    scopes: List[str] = Field(
        default_factory=lambda: [
            "User.Read",
            "Mail.ReadWrite",
            "Calendars.ReadWrite",
            "ChannelMessage.Send.All",
            "Files.ReadWrite.All"
        ],
        description="Microsoft Graph OAuth scopes"
    )

    # Features
    enable_mail: bool = True
    enable_calendar: bool = True
    enable_teams: bool = True
    enable_drive: bool = True

    # Cache
    cache_ttl: int = Field(default=300, description="Token cache TTL in seconds")

    @validator('client_secret')
    def validate_app_only_credentials(cls, v, values):
        """Validate that client_secret is provided for app_only mode."""
        if values.get('auth_mode') == 'app_only' and not v:
            raise ValueError("client_secret is required for app_only authentication")
        return v


class MicrosoftGraphToolkit(Toolkit):
    """
    Microsoft Graph API integration for Agno agents.

    This toolkit provides integration with Microsoft 365 services including
    Mail, Calendar, Teams, and OneDrive/SharePoint through Microsoft Graph API.

    Environment Variables:
        MICROSOFT_GRAPH_CLIENT_ID: Entra ID application (client) ID
        MICROSOFT_GRAPH_TENANT_ID: Azure AD tenant ID
        MICROSOFT_GRAPH_CLIENT_SECRET: Client secret (for app-only flow)
        MICROSOFT_GRAPH_REDIRECT_URI: OAuth redirect URI (for delegated flow)

    Example:
        ```python
        from agno.agent import Agent
        from agno.tools.microsoft_graph import MicrosoftGraphToolkit

        toolkit = MicrosoftGraphToolkit(
            client_id="your-client-id",
            tenant_id="your-tenant-id",
            auth_mode="delegated"
        )

        agent = Agent(tools=[toolkit])
        ```
    """

    _requires_connect: bool = True

    def __init__(
        self,
        client_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auth_mode: Literal["delegated", "app_only"] = "delegated",
        scopes: Optional[List[str]] = None,
        enable_mail: bool = True,
        enable_calendar: bool = True,
        enable_teams: bool = True,
        enable_drive: bool = True,
        cache_ttl: int = 300,
        **kwargs
    ):
        # Get configuration from environment or parameters
        client_id = client_id or getenv("MICROSOFT_GRAPH_CLIENT_ID")
        tenant_id = tenant_id or getenv("MICROSOFT_GRAPH_TENANT_ID")
        client_secret = client_secret or getenv("MICROSOFT_GRAPH_CLIENT_SECRET")
        redirect_uri = redirect_uri or getenv("MICROSOFT_GRAPH_REDIRECT_URI", "http://localhost:5000/callback")

        # Validate required fields
        if not client_id:
            raise ValueError("client_id is required. Set MICROSOFT_GRAPH_CLIENT_ID environment variable or pass client_id parameter.")
        if not tenant_id:
            raise ValueError("tenant_id is required. Set MICROSOFT_GRAPH_TENANT_ID environment variable or pass tenant_id parameter.")

        # Create configuration
        self.config = GraphConfig(
            client_id=client_id,
            tenant_id=tenant_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            auth_mode=auth_mode,
            scopes=scopes,
            enable_mail=enable_mail,
            enable_calendar=enable_calendar,
            enable_teams=enable_teams,
            enable_drive=enable_drive,
            cache_ttl=cache_ttl
        )

        # Initialize authentication manager
        self.auth_manager = GraphAuthenticationManager(self.config)

        # Build tools list
        tools: List[Any] = []

        if enable_mail:
            mail_tools = GraphMailTools(
                auth_manager=self.auth_manager,
                cache_ttl=cache_ttl
            )
            tools.extend([
                mail_tools.send_email,
                mail_tools.get_emails,
                mail_tools.reply_email,
                mail_tools.get_email
            ])

        if enable_calendar:
            calendar_tools = GraphCalendarTools(
                auth_manager=self.auth_manager,
                cache_ttl=cache_ttl
            )
            tools.extend([
                calendar_tools.get_events,
                calendar_tools.create_event,
                calendar_tools.update_event,
                calendar_tools.delete_event
            ])

        if enable_teams:
            teams_tools = GraphTeamsTools(
                auth_manager=self.auth_manager,
                cache_ttl=cache_ttl
            )
            tools.extend([
                teams_tools.send_message,
                teams_tools.list_channels,
                teams_tools.get_chat_history
            ])

        if enable_drive:
            drive_tools = GraphDriveTools(
                auth_manager=self.auth_manager,
                cache_ttl=cache_ttl
            )
            tools.extend([
                drive_tools.list_files,
                drive_tools.upload_file,
                drive_tools.download_file,
                drive_tools.search_files
            ])

        # Initialize parent class
        super().__init__(
            name="microsoft_graph",
            tools=tools,
            instructions=self._get_instructions(),
            **kwargs
        )

    def _get_instructions(self) -> str:
        """Get instructions for the toolkit."""
        instructions = "You have access to Microsoft 365 services through Microsoft Graph API."

        if self.config.enable_mail:
            instructions += "\n- Mail: Send, read, and reply to emails"

        if self.config.enable_calendar:
            instructions += "\n- Calendar: View, create, and manage events"

        if self.config.enable_teams:
            instructions += "\n- Teams: Send messages and view channels"

        if self.config.enable_drive:
            instructions += "\n- Drive: Access files in OneDrive and SharePoint"

        return instructions

    def connect(self) -> None:
        """Establish connection to Microsoft Graph."""
        logger.info(f"Connecting to Microsoft Graph (tenant: {self.config.tenant_id})")
        self.auth_manager.authenticate()

    def close(self) -> None:
        """Close connection and cleanup resources."""
        logger.info("Closing Microsoft Graph connection")
        self.auth_manager.dispose()
```

---

## 2. Authentication Implementation

### 2.1 Authentication Manager

```python
# libs/agno/agno/tools/microsoft_graph/auth/manager.py

import time
from typing import Optional
from datetime import datetime, timedelta

from azure.identity import (
    DeviceCodeCredential,
    ClientSecretCredential,
    ClientCertificateCredential,
    AuthorizationCodeCredential
)
from msgraph.core import GraphServiceClient

from agno.utils.log import logger
from ..models.config import GraphConfig


class GraphAuthenticationManager:
    """
    Manages authentication and token lifecycle for Microsoft Graph.

    Handles:
    - Multiple authentication flows (delegated, app-only, OBO)
    - Automatic token refresh
    - Token caching
    - Error handling
    """

    def __init__(self, config: GraphConfig):
        self.config = config
        self.client: Optional[GraphServiceClient] = None
        self._token_expiry: Optional[datetime] = None
        self._credential = self._build_credential()

    def _build_credential(self):
        """Build appropriate Azure Identity credential."""
        if self.config.auth_mode == "delegated":
            return self._build_delegated_credential()
        else:
            return self._build_app_only_credential()

    def _build_delegated_credential(self):
        """Build credential for delegated (user) authentication."""
        if self.config.certificate_path:
            logger.warning("Certificate not supported for delegated flow, using device code")
            return DeviceCodeCredential(
                client_id=self.config.client_id,
                tenant_id=self.config.tenant_id
            )
        else:
            # For interactive scenarios, use authorization code flow
            # For non-interactive, use device code flow
            return AuthorizationCodeCredential(
                client_id=self.config.client_id,
                tenant_id=self.config.tenant_id,
                redirect_uri=self.config.redirect_uri
            )

    def _build_app_only_credential(self):
        """Build credential for app-only authentication."""
        if self.config.certificate_path:
            logger.info("Using certificate-based authentication")
            return ClientCertificateCredential(
                tenant_id=self.config.tenant_id,
                client_id=self.config.client_id,
                certificate_path=self.config.certificate_path
            )
        else:
            logger.info("Using client secret authentication")
            return ClientSecretCredential(
                tenant_id=self.config.tenant_id,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret
            )

    def authenticate(self) -> GraphServiceClient:
        """
        Authenticate and return GraphServiceClient.

        Handles token refresh automatically.
        """
        if self._is_token_valid():
            return self.client

        logger.info("Acquiring new access token")
        self.client = GraphServiceClient(
            credentials=self._credential,
            scopes=self.config.scopes
        )
        self._token_expiry = datetime.now() + timedelta(seconds=self.config.cache_ttl)

        return self.client

    def _is_token_valid(self) -> bool:
        """Check if current token is still valid."""
        if not self.client or not self._token_expiry:
            return False

        # Add 5 minute buffer before expiry
        return datetime.now() < (self._token_expiry - timedelta(minutes=5))

    def get_client(self) -> GraphServiceClient:
        """Get authenticated Graph client."""
        return self.authenticate()

    def dispose(self):
        """Dispose of resources."""
        self.client = None
        self._token_expiry = None
```

---

## 3. Mail Tools Implementation

### 3.1 GraphMailTools

```python
# libs/agno/agno/tools/microsoft_graph/tools/mail.py

import json
from typing import Any, Dict, List, Optional
from email.utils import formataddr

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from msgraph.generated.models.message import Message
    from msgraph.generated.models.item_body import ItemBody
    from msgraph.generated.models.recipient import Recipient
    from msgraph.generated.models.email_address import EmailAddress
except ImportError:
    raise ImportError(
        "Microsoft Graph SDK not found. "
        "Install with: pip install msgraph-sdk"
    )

from ..auth.manager import GraphAuthenticationManager


class GraphMailTools(Toolkit):
    """
    Microsoft Graph Mail tools.

    Provides functionality for:
    - Sending emails
    - Reading emails
    - Replying to emails
    - Managing folders
    """

    def __init__(
        self,
        auth_manager: GraphAuthenticationManager,
        cache_ttl: int = 300,
        **kwargs
    ):
        self.auth_manager = auth_manager
        self.cache_ttl = cache_ttl

        tools = [
            self.send_email,
            self.get_emails,
            self.reply_email,
            self.get_email
        ]

        super().__init__(
            name="graph_mail",
            tools=tools,
            **kwargs
        )

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        importance: str = "normal"
    ) -> str:
        """
        Send an email using Microsoft Graph.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (HTML supported)
            cc: Optional CC recipient
            bcc: Optional BCC recipient
            importance: Email importance (low, normal, high)

        Returns:
            JSON string with the result including message ID

        Example:
            ```python
            result = send_email(
                to="user@example.com",
                subject="Meeting Reminder",
                body="Don't forget our meeting tomorrow at 2pm"
            )
            ```
        """
        try:
            client = self.auth_manager.get_client()

            # Create message
            message = Message()
            message.subject = subject

            # Set body
            message_body = ItemBody()
            message_body.content = body
            message_body.content_type = "HTML"
            message.body = message_body

            # Set recipients
            to_recipient = Recipient()
            to_recipient.email_address = EmailAddress()
            to_recipient.email_address.address = to
            message.to_recipients = [to_recipient]

            if cc:
                cc_recipient = Recipient()
                cc_recipient.email_address = EmailAddress()
                cc_recipient.email_address.address = cc
                message.cc_recipients = [cc_recipient]

            if bcc:
                bcc_recipient = Recipient()
                bcc_recipient.email_address = EmailAddress()
                bcc_recipient.email_address.address = bcc
                message.bcc_recipients = [bcc_recipient]

            # Set importance
            message.importance = importance

            # Send email
            request_body = {
                "message": message
            }

            client.me.send_mail.post(request_body)

            logger.info(f"Email sent successfully to {to}")

            return json.dumps({
                "success": True,
                "message": "Email sent successfully",
                "to": to,
                "subject": subject
            })

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def get_emails(
        self,
        folder: str = "inbox",
        limit: int = 20,
        include_drafts: bool = False
    ) -> str:
        """
        Get emails from a folder.

        Args:
            folder: Folder name (inbox, sent, drafts, etc.)
            limit: Maximum number of emails to retrieve
            include_drafts: Whether to include draft emails

        Returns:
            JSON string with list of emails

        Example:
            ```python
            emails = get_emails(folder="inbox", limit=10)
            ```
        """
        try:
            client = self.auth_manager.get_client()

            # Build query
            folder_mapping = {
                "inbox": "Inbox",
                "sent": "SentItems",
                "drafts": "Drafts",
                "deleted": "DeletedItems",
                "archive": "Archive"
            }

            folder_name = folder_mapping.get(folder.lower(), "Inbox")

            # Get messages
            request_config = {
                "query_parameters": {
                    "$top": limit,
                    "$select": "id,subject,from,receivedDateTime,body,importance,isRead",
                    "$orderby": "receivedDateTime desc"
                }
            }

            messages = client.me.mail_folders.by_mail_folder_id(folder_name).messages.get(request_config)

            result = []
            for msg in messages.value:
                result.append({
                    "id": msg.id,
                    "subject": msg.subject,
                    "from": msg.from.email_address.address if msg.from else None,
                    "received": msg.received_date_time.isoformat() if msg.received_date_time else None,
                    "importance": msg.importance,
                    "is_read": msg.is_read,
                    "body_preview": msg.body.content[:200] if msg.body else None
                })

            return json.dumps({
                "success": True,
                "folder": folder,
                "count": len(result),
                "emails": result
            })

        except Exception as e:
            logger.error(f"Failed to get emails: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def reply_email(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False
    ) -> str:
        """
        Reply to an email.

        Args:
            message_id: ID of the message to reply to
            body: Reply body
            reply_all: Whether to reply to all recipients

        Returns:
            JSON string with the result

        Example:
            ```python
            result = reply_email(
                message_id="ABC123",
                body="Thank you for your email. I'll review and get back to you."
            )
            ```
        """
        try:
            client = self.auth_manager.get_client()

            message_body = ItemBody()
            message_body.content = body
            message_body.content_type = "HTML"

            request_body = {
                "message": {
                    "body": message_body
                }
            }

            if reply_all:
                client.me.messages.by_message_id(message_id).reply_all.post(request_body)
            else:
                client.me.messages.by_message_id(message_id).reply.post(request_body)

            logger.info(f"Reply sent for message {message_id}")

            return json.dumps({
                "success": True,
                "message": "Reply sent successfully"
            })

        except Exception as e:
            logger.error(f"Failed to reply to email: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def get_email(self, message_id: str) -> str:
        """
        Get a specific email by ID.

        Args:
            message_id: ID of the message to retrieve

        Returns:
            JSON string with email details

        Example:
            ```python
            email = get_email(message_id="ABC123")
            ```
        """
        try:
            client = self.auth_manager.get_client()

            request_config = {
                "query_parameters": {
                    "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,attachments"
                }
            }

            message = client.me.messages.by_message_id(message_id).get(request_config)

            result = {
                "id": message.id,
                "subject": message.subject,
                "from": {
                    "email": message.from.email_address.address,
                    "name": message.from.email_address.name
                } if message.from else None,
                "to": [
                    {"email": r.email_address.address, "name": r.email_address.name}
                    for r in message.to_recipients
                ] if message.to_recipients else [],
                "cc": [
                    {"email": r.email_address.address, "name": r.email_address.name}
                    for r in message.cc_recipients
                ] if message.cc_recipients else [],
                "received": message.received_date_time.isoformat() if message.received_date_time else None,
                "body": message.body.content if message.body else None,
                "has_attachments": message.has_attachments if hasattr(message, 'has_attachments') else False
            }

            return json.dumps({
                "success": True,
                "email": result
            })

        except Exception as e:
            logger.error(f"Failed to get email: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })
```

---

## 4. Calendar Tools Implementation

### 4.1 GraphCalendarTools

```python
# libs/agno/agno/tools/microsoft_graph/tools/calendar.py

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from msgraph.generated.models.event import Event
    from msgraph.generated.models.item_body import ItemBody
    from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
    from msgraph.generated.models.location import Location
except ImportError:
    raise ImportError(
        "Microsoft Graph SDK not found. "
        "Install with: pip install msgraph-sdk"
    )

from ..auth.manager import GraphAuthenticationManager


class GraphCalendarTools(Toolkit):
    """
    Microsoft Graph Calendar tools.

    Provides functionality for:
    - Listing calendar events
    - Creating events
    - Updating events
    - Deleting events
    """

    def __init__(
        self,
        auth_manager: GraphAuthenticationManager,
        cache_ttl: int = 300,
        **kwargs
    ):
        self.auth_manager = auth_manager
        self.cache_ttl = cache_ttl

        tools = [
            self.get_events,
            self.create_event,
            self.update_event,
            self.delete_event
        ]

        super().__init__(
            name="graph_calendar",
            tools=tools,
            **kwargs
        )

    def get_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50
    ) -> str:
        """
        Get calendar events for a date range.

        Args:
            start_date: Start date in ISO format (YYYY-MM-DD)
            end_date: End date in ISO format (YYYY-MM-DD)
            limit: Maximum number of events to retrieve

        Returns:
            JSON string with list of events

        Example:
            ```python
            events = get_events(
                start_date="2025-03-01",
                end_date="2025-03-07",
                limit=20
            )
            ```
        """
        try:
            client = self.auth_manager.get_client()

            # Default to today and next 7 days
            if not start_date:
                start_date = datetime.now().strftime("%Y-%m-%d")
            if not end_date:
                end_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

            # Build query
            request_config = {
                "query_parameters": {
                    "$top": limit,
                    "$select": "id,subject,start,end,location,attendees,body,importance,isOnlineMeeting,onlineMeetingUrl",
                    "$orderby": "start/dateTime"
                },
                "headers": {
                    "Prefer": 'outlook.body-content-type="text"'
                }
            }

            # Get events from calendar view
            events = client.me.calendar_view.get(
                start_date=start_date,
                end_date=end_date,
                request_configuration=request_config
            )

            result = []
            for event in events.value:
                result.append({
                    "id": event.id,
                    "subject": event.subject,
                    "start": {
                        "datetime": event.start.date_time.isoformat() if event.start else None,
                        "timezone": event.start.time_zone if event.start else None
                    } if event.start else None,
                    "end": {
                        "datetime": event.end.date_time.isoformat() if event.end else None,
                        "timezone": event.end.time_zone if event.end else None
                    } if event.end else None,
                    "location": event.location.display_name if event.location else None,
                    "attendees": [
                        {
                            "email": a.email_address.address,
                            "name": a.email_address.name,
                            "status": a.status.response if a.status else None
                        }
                        for a in event.attendees
                    ] if event.attendees else [],
                    "importance": event.importance,
                    "is_online": event.is_online_meeting if hasattr(event, 'is_online_meeting') else False,
                    "online_meeting_url": event.online_meeting_url if hasattr(event, 'online_meeting_url') else None
                })

            return json.dumps({
                "success": True,
                "start_date": start_date,
                "end_date": end_date,
                "count": len(result),
                "events": result
            })

        except Exception as e:
            logger.error(f"Failed to get events: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def create_event(
        self,
        subject: str,
        start: str,
        end: str,
        body: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        is_online_meeting: bool = False
    ) -> str:
        """
        Create a calendar event.

        Args:
            subject: Event subject/title
            start: Start datetime in ISO format
            end: End datetime in ISO format
            body: Event description
            location: Event location
            attendees: List of attendee email addresses
            is_online_meeting: Whether to create as Teams meeting

        Returns:
            JSON string with created event details

        Example:
            ```python
            result = create_event(
                subject="Team Standup",
                start="2025-03-06T10:00:00",
                end="2025-03-06T10:30:00",
                body="Daily team standup meeting",
                location="Conference Room A",
                attendees=["user1@example.com", "user2@example.com"],
                is_online_meeting=True
            )
            ```
        """
        try:
            client = self.auth_manager.get_client()

            # Create event
            event = Event()
            event.subject = subject

            # Set times
            start_time = DateTimeTimeZone()
            start_time.date_time = start
            start_time.time_zone = "UTC"
            event.start = start_time

            end_time = DateTimeTimeZone()
            end_time.date_time = end
            end_time.time_zone = "UTC"
            event.end = end_time

            # Set body if provided
            if body:
                event_body = ItemBody()
                event_body.content = body
                event_body.content_type = "HTML"
                event.body = event_body

            # Set location if provided
            if location:
                event_location = Location()
                event_location.display_name = location
                event.location = event_location

            # Set attendees if provided
            if attendees:
                from msgraph.generated.models.attendee import Attendee
                from msgraph.generated.models.email_address import EmailAddress

                event.attendees = []
                for email in attendees:
                    attendee = Attendee()
                    attendee.email_address = EmailAddress()
                    attendee.email_address.address = email
                    event.attendees.append(attendee)

            # Set online meeting
            event.is_online_meeting = is_online_meeting

            # Create event
            created_event = client.me.events.post(event)

            logger.info(f"Event created: {created_event.id}")

            return json.dumps({
                "success": True,
                "message": "Event created successfully",
                "event_id": created_event.id,
                "subject": created_event.subject
            })

        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def update_event(
        self,
        event_id: str,
        subject: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        body: Optional[str] = None,
        location: Optional[str] = None
    ) -> str:
        """
        Update an existing calendar event.

        Args:
            event_id: ID of the event to update
            subject: New subject
            start: New start datetime in ISO format
            end: New end datetime in ISO format
            body: New body/description
            location: New location

        Returns:
            JSON string with updated event details

        Example:
            ```python
            result = update_event(
                event_id="ABC123",
                subject="Updated Meeting Title",
                start="2025-03-06T11:00:00"
            )
            ```
        """
        try:
            client = self.auth_manager.get_client()

            # Get existing event
            existing_event = client.me.events.by_event_id(event_id).get()

            # Create update body with only provided fields
            request_body = {}

            if subject is not None:
                request_body["subject"] = subject

            if start is not None:
                start_time = DateTimeTimeZone()
                start_time.date_time = start
                start_time.time_zone = "UTC"
                request_body["start"] = start_time

            if end is not None:
                end_time = DateTimeTimeZone()
                end_time.date_time = end
                end_time.time_zone = "UTC"
                request_body["end"] = end_time

            if body is not None:
                event_body = ItemBody()
                event_body.content = body
                event_body.content_type = "HTML"
                request_body["body"] = event_body

            if location is not None:
                event_location = Location()
                event_location.display_name = location
                request_body["location"] = event_location

            # Update event
            updated_event = client.me.events.by_event_id(event_id).patch(request_body)

            logger.info(f"Event updated: {event_id}")

            return json.dumps({
                "success": True,
                "message": "Event updated successfully",
                "event_id": updated_event.id
            })

        except Exception as e:
            logger.error(f"Failed to update event: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def delete_event(self, event_id: str) -> str:
        """
        Delete a calendar event.

        Args:
            event_id: ID of the event to delete

        Returns:
            JSON string with result

        Example:
            ```python
            result = delete_event(event_id="ABC123")
            ```
        """
        try:
            client = self.auth_manager.get_client()

            client.me.events.by_event_id(event_id).delete()

            logger.info(f"Event deleted: {event_id}")

            return json.dumps({
                "success": True,
                "message": "Event deleted successfully"
            })

        except Exception as e:
            logger.error(f"Failed to delete event: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })
```

---

## 5. Usage Examples

### 5.1 Basic Agent with Microsoft Graph

```python
# cookbook/92_integrations/microsoft_graph/basic_agent.py

from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from agno.models.openai import OpenAIChat

# Create Microsoft Graph toolkit
graph_toolkit = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    auth_mode="delegated"
)

# Create agent with Graph integration
agent = Agent(
    name="Microsoft 365 Assistant",
    model=OpenAIChat(id="gpt-4"),
    tools=[graph_toolkit],
    instructions="""
    You are a helpful Microsoft 365 assistant. You can help users with:
    - Managing their email
    - Scheduling and managing calendar events
    - Sending Teams messages
    - Accessing files in OneDrive and SharePoint

    Always be clear and helpful. Ask for clarification when needed.
    """
)

# Run the agent
agent.run("What meetings do I have scheduled for this week?")
```

### 5.2 Email Agent Example

```python
# cookbook/92_integrations/microsoft_graph/email_agent.py

from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from agno.models.anthropic import Claude

# Create toolkit with only mail enabled
graph_toolkit = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    auth_mode="delegated",
    enable_mail=True,
    enable_calendar=False,
    enable_teams=False,
    enable_drive=False
)

# Create email-focused agent
email_agent = Agent(
    name="Email Assistant",
    model=Claude(id="claude-3-5-sonnet-20241022"),
    tools=[graph_toolkit],
    instructions="""
    You are an email assistant. You can:
    - Read and summarize emails from the inbox
    - Send new emails
    - Reply to existing emails

    Best practices:
    - Always confirm before sending emails
    - Summarize long email threads
    - Highlight important information
    - Ask for missing information when composing emails
    """
)

# Example: Check inbox
email_agent.run("Check my inbox and summarize any important emails from today")

# Example: Compose and send email
email_agent.run("Send an email to john@example.com asking about the project status")
```

### 5.3 Calendar Agent Example

```python
# cookbook/92_integrations/microsoft_graph/calendar_agent.py

from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from agno.models.openai import OpenAIChat

# Create toolkit with calendar enabled
graph_toolkit = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    auth_mode="delegated",
    enable_mail=False,
    enable_calendar=True,
    enable_teams=False,
    enable_drive=False
)

# Create calendar-focused agent
calendar_agent = Agent(
    name="Calendar Assistant",
    model=OpenAIChat(id="gpt-4"),
    tools=[graph_toolkit],
    instructions="""
    You are a calendar assistant. You can:
    - View calendar events
    - Create new meetings
    - Update existing events
    - Schedule appointments

    Best practices:
    - Check for conflicts before scheduling
    - Include all relevant details (time, location, attendees)
    - Confirm before making changes
    - Suggest optimal meeting times
    """
)

# Example: Check schedule
calendar_agent.run("What's on my schedule for tomorrow?")

# Example: Schedule meeting
calendar_agent.run("Schedule a 1-hour meeting with the marketing team next Tuesday at 2pm")
```

### 5.4 Multi-Purpose Agent

```python
# cookbook/92_integrations/microsoft_graph/multi_purpose_agent.py

from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from agno.models.openai import OpenAIChat

# Create full-featured toolkit
graph_toolkit = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    auth_mode="delegated"
)

# Create comprehensive M365 assistant
m365_assistant = Agent(
    name="Microsoft 365 Assistant",
    model=OpenAIChat(id="gpt-4-turbo"),
    tools=[graph_toolkit],
    instructions="""
    You are a comprehensive Microsoft 365 assistant. You can help with:

    EMAIL:
    - Read, send, and reply to emails
    - Organize inbox
    - Summarize email threads

    CALENDAR:
    - View and manage events
    - Schedule meetings
    - Check availability

    TEAMS:
    - Send messages to channels
    - View chat history
    - List channels and teams

    FILES:
    - Access OneDrive and SharePoint
    - Search for files
    - Upload and download files

    GUIDELINES:
    - Always confirm before taking actions
    - Be proactive in suggesting actions
    - Summarize information clearly
    - Ask for clarification when needed
    - Respect user's privacy and permissions
    """
)

# Interactive loop
while True:
    user_input = input("\nHow can I help you with Microsoft 365? ")
    if user_input.lower() in ['exit', 'quit', 'bye']:
        print("Goodbye!")
        break

    response = m365_assistant.run(user_input)
    print(f"\n{response.content}")
```

---

## 6. Testing Examples

### 6.1 Unit Test Example

```python
# tests/unit/tools/test_graph_mail.py

import pytest
from unittest.mock import Mock, MagicMock, patch
from agno.tools.microsoft_graph.tools.mail import GraphMailTools

class TestGraphMailTools:

    @pytest.fixture
    def mock_auth_manager(self):
        """Create mock authentication manager."""
        manager = Mock()
        manager.get_client.return_value = Mock()
        return manager

    @pytest.fixture
    def mail_tools(self, mock_auth_manager):
        """Create GraphMailTools with mocked auth."""
        return GraphMailTools(auth_manager=mock_auth_manager)

    def test_send_email_success(self, mail_tools, mock_auth_manager):
        """Test successful email sending."""
        # Arrange
        mock_client = mock_auth_manager.get_client.return_value
        mock_client.me.send_mail.post.return_value = None

        # Act
        result = mail_tools.send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Test Body"
        )

        # Assert
        import json
        result_dict = json.loads(result)
        assert result_dict["success"] is True
        assert result_dict["to"] == "test@example.com"
        assert result_dict["subject"] == "Test Subject"
        mock_client.me.send_mail.post.assert_called_once()

    def test_send_email_with_cc_bcc(self, mail_tools, mock_auth_manager):
        """Test email sending with CC and BCC."""
        # Arrange
        mock_client = mock_auth_manager.get_client.return_value

        # Act
        result = mail_tools.send_email(
            to="to@example.com",
            subject="Test",
            body="Body",
            cc="cc@example.com",
            bcc="bcc@example.com"
        )

        # Assert
        mock_client.me.send_mail.post.assert_called_once()
        call_args = mock_client.me.send_mail.post.call_args

    @pytest.mark.parametrize("folder", ["inbox", "sent", "drafts", "deleted"])
    def test_get_emails_different_folders(self, mail_tools, mock_auth_manager, folder):
        """Test getting emails from different folders."""
        # Arrange
        mock_client = mock_auth_manager.get_client.return_value
        mock_messages = Mock()
        mock_messages.value = []
        mock_client.me.mail_folders.by_mail_folder_id.return_value.messages.get.return_value = mock_messages

        # Act
        result = mail_tools.get_emails(folder=folder, limit=10)

        # Assert
        import json
        result_dict = json.loads(result)
        assert result_dict["success"] is True
        assert result_dict["folder"] == folder
```

### 6.2 Integration Test Example

```python
# tests/integration/test_graph_integration.py

import pytest
import os
from agno.agent import Agent
from agno.tools.microsoft_graph import MicrosoftGraphToolkit
from agno.models.openai import OpenAIChat

@pytest.mark.integration
class TestGraphIntegration:

    @pytest.fixture
    def graph_toolkit(self):
        """Create real Graph toolkit for integration testing."""
        return MicrosoftGraphToolkit(
            client_id=os.getenv("TEST_GRAPH_CLIENT_ID"),
            tenant_id=os.getenv("TEST_GRAPH_TENANT_ID"),
            client_secret=os.getenv("TEST_GRAPH_CLIENT_SECRET"),
            auth_mode="app_only"  # Use app-only for testing
        )

    def test_agent_with_graph_tools(self, graph_toolkit):
        """Test agent using Graph tools."""
        # Arrange
        agent = Agent(
            name="Test Agent",
            model=OpenAIChat(id="gpt-4"),
            tools=[graph_toolkit]
        )

        # Act
        response = agent.run("List my calendar events for this week")

        # Assert
        assert response.content is not None
        # Additional assertions based on actual response
```

---

## 7. Configuration Examples

### 7.1 Environment Variables File

```bash
# .env file for Microsoft Graph configuration

# Required - App Registration
MICROSOFT_GRAPH_CLIENT_ID=your-client-id-here
MICROSOFT_GRAPH_TENANT_ID=your-tenant-id-here

# For app-only authentication
MICROSOFT_GRAPH_CLIENT_SECRET=your-client-secret-here

# For delegated authentication
MICROSOFT_GRAPH_REDIRECT_URI=http://localhost:5000/callback

# Optional - Certificate-based authentication (recommended for production)
# MICROSOFT_GRAPH_CERTIFICATE_PATH=/path/to/certificate.pem

# Optional - Cache configuration
MICROSOFT_GRAPH_CACHE_TTL=300
MICROSOFT_GRAPH_CACHE_DIR=/tmp/graph_cache

# Optional - Feature flags
MICROSOFT_GRAPH_ENABLE_MAIL=true
MICROSOFT_GRAPH_ENABLE_CALENDAR=true
MICROSOFT_GRAPH_ENABLE_TEAMS=true
MICROSOFT_GRAPH_ENABLE_DRIVE=true
```

### 7.2 Programmatic Configuration

```python
from agno.tools.microsoft_graph import MicrosoftGraphToolkit

# Minimal configuration (uses environment variables)
toolkit = MicrosoftGraphToolkit()

# Explicit configuration
toolkit = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    client_secret="your-client-secret",
    auth_mode="app_only"
)

# Selective feature enablement
toolkit = MicrosoftGraphToolkit(
    client_id="your-client-id",
    tenant_id="your-tenant-id",
    auth_mode="delegated",
    enable_mail=True,
    enable_calendar=True,
    enable_teams=False,
    enable_drive=False
)
```

---

## 8. Error Handling Patterns

### 8.1 Custom Error Handler

```python
from typing import Dict, Any
import json
from msgraph.core.exceptions import GraphError

class GraphErrorHandler:
    """Handle Microsoft Graph API errors gracefully."""

    ERROR_MESSAGES = {
        "InvalidAuthenticationToken": "Your session has expired. Please re-authenticate.",
        "Unauthorized": "You don't have permission to perform this action.",
        "Forbidden": "Access to this resource is forbidden.",
        "ResourceNotFound": "The requested resource was not found.",
        "TooManyRequests": "You've exceeded the rate limit. Please try again later.",
        "MailboxNotEnabledForRESTAPI": "The mailbox is not enabled for REST API access.",
    }

    @classmethod
    def handle_error(cls, error: Exception) -> Dict[str, Any]:
        """Convert exception to user-friendly error response."""
        if isinstance(error, GraphError):
            error_code = error.error_code if hasattr(error, 'error_code') else "UnknownError"
            message = cls.ERROR_MESSAGES.get(error_code, str(error))

            return {
                "success": False,
                "error": error_code,
                "message": message,
                "retry_after": getattr(error, 'retry_after', None)
            }
        else:
            return {
                "success": False,
                "error": "UnexpectedError",
                "message": "An unexpected error occurred. Please try again."
            }

# Usage in tools
def send_email(self, to: str, subject: str, body: str) -> str:
    try:
        # ... send email logic ...
        return json.dumps({"success": True, "message": "Email sent"})
    except Exception as e:
        error_response = GraphErrorHandler.handle_error(e)
        return json.dumps(error_response)
```

---

This implementation guide provides complete code examples for implementing the Microsoft Graph connector for Agno. The code follows Agno's patterns and Microsoft's best practices for Graph API integration.
