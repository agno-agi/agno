"""
Gmail Toolkit for interacting with Gmail API

Required Environment Variables:
-----------------------------
- GOOGLE_CLIENT_ID: Google OAuth client ID
- GOOGLE_CLIENT_SECRET: Google OAuth client secret
- GOOGLE_PROJECT_ID: Google Cloud project ID
- GOOGLE_REDIRECT_URI: Google OAuth redirect URI (default: http://localhost)

How to Get These Credentials:
---------------------------
1. Go to Google Cloud Console (https://console.cloud.google.com)
2. Create a new project or select an existing one
3. Enable the Gmail API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Gmail API"
   - Click "Enable"

4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Go through the OAuth consent screen setup
   - Give it a name and click "Create"
   - You'll receive:
     * Client ID (GOOGLE_CLIENT_ID)
     * Client Secret (GOOGLE_CLIENT_SECRET)
   - The Project ID (GOOGLE_PROJECT_ID) is visible in the project dropdown at the top of the page

5. Add auth redirect URI:
   - Go to https://console.cloud.google.com/auth/clients and add the redirect URI as http://127.0.0.1/

6. Set up environment variables:
   Create a .envrc file in your project root with:
   ```
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://127.0.0.1/  # Default value
   ```

Note: The first time you run the application, it will open a browser window for OAuth authentication.
A token.json file will be created to store the authentication credentials for future use.

Service Account Authentication (Alternative):
---------------------------------------------
For server/bot deployments where no browser is available, use a Google service account
with domain-wide delegation instead of OAuth.

1. Create a service account in Google Cloud Console > "IAM & Admin" > "Service Accounts"
2. Download the JSON key file
3. In Google Workspace Admin Console, go to Security > API Controls > Domain-wide Delegation
4. Add the service account's client_id with the Gmail scopes your agent needs
5. Set environment variables:
   ```
   export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account-key.json
   export GOOGLE_DELEGATED_USER=user@yourdomain.com
   ```

When service_account_path (or GOOGLE_SERVICE_ACCOUNT_FILE) is set, OAuth is skipped entirely.
The delegated_user specifies which mailbox the service account will access.
"""

import base64
import json
import mimetypes
import re
import tempfile
import textwrap
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from agno.tools import Toolkit
from agno.tools.google.auth import google_authenticate
from agno.utils.log import log_debug, log_error

try:
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client library for Python not found , install it using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


authenticate = google_authenticate("gmail")


def validate_email(email: str) -> bool:
    """Validate email format."""
    email = email.strip()
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


GMAIL_QUERY_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Gmail tools for reading, composing, and organizing emails.

    ## Gmail Query Syntax
    Use these operators in search and context query parameters:
    - `from:user@example.com` / `to:user@example.com` — filter by sender/recipient
    - `subject:"meeting notes"` — filter by subject
    - `is:unread` / `is:starred` / `is:important` — filter by status
    - `has:attachment` — emails with attachments
    - `newer_than:7d` / `older_than:1m` — relative date (d=days, m=months, y=years)
    - `after:2024/01/01` / `before:2024/12/31` — absolute date range
    - `label:work` — filter by label
    - `from:me` — emails sent by the user
    - Combine with spaces (AND): `from:me newer_than:7d has:attachment`""")


class GmailTools(Toolkit):
    # Default scopes for Gmail API access
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]

    def __init__(
        self,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        port: Optional[int] = None,
        login_hint: Optional[str] = None,
        include_html: bool = False,
        max_body_length: Optional[int] = None,
        attachment_dir: Optional[str] = None,
        # Reading
        get_latest_emails: bool = True,
        get_emails_from_user: bool = True,
        get_unread_emails: bool = True,
        get_starred_emails: bool = True,
        get_emails_by_context: bool = True,
        get_emails_by_date: bool = True,
        get_emails_by_thread: bool = True,
        search_emails: bool = True,
        # Management
        mark_email_as_read: bool = True,
        mark_email_as_unread: bool = True,
        star_email: bool = True,
        unstar_email: bool = True,
        archive_email: bool = False,
        # Composing
        create_draft_email: bool = True,
        send_email: bool = True,
        send_email_reply: bool = True,
        # Labels
        list_custom_labels: bool = True,
        apply_label: bool = True,
        remove_label: bool = True,
        delete_custom_label: bool = True,
        # Thread & message tools
        get_message: bool = True,
        get_thread: bool = True,
        search_threads: bool = True,
        modify_thread_labels: bool = False,
        trash_thread: bool = False,
        get_draft: bool = True,
        list_drafts: bool = True,
        send_draft: bool = False,
        update_draft: bool = True,
        list_labels: bool = False,
        modify_message_labels: bool = False,
        trash_message: bool = False,
        download_attachment: bool = False,
        max_batch_size: int = 10,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """Initialize GmailTools and authenticate with Gmail API

        Args:
            creds (Optional[Union[Credentials, ServiceAccountCredentials]]): Pre-fetched credentials. Use this to skip a new auth flow. Defaults to None.
            credentials_path (Optional[str]): Path to credentials file. Defaults to None.
            token_path (Optional[str]): Path to token file. Defaults to None.
            service_account_path (Optional[str]): Path to a service account JSON key file. When provided (or GOOGLE_SERVICE_ACCOUNT_FILE env var is set), service account auth is used instead of OAuth. Requires delegated_user for Gmail.
            delegated_user (Optional[str]): Email of the user to impersonate via domain-wide delegation. Required when using service account auth. Can also be set via GOOGLE_DELEGATED_USER env var.
            scopes (Optional[List[str]]): Custom OAuth scopes. If None, uses DEFAULT_SCOPES.
            port (Optional[int]): Port to use for OAuth authentication. Defaults to None.
            login_hint (Optional[str]): Email to pre-select in the OAuth consent screen. Defaults to None.
            include_html (bool): If True, return raw HTML body instead of stripping tags. Defaults to False.
            max_body_length (Optional[int]): Truncate message bodies to this length. Defaults to None (no truncation).
            attachment_dir (Optional[str]): Directory to save downloaded attachments. Defaults to a temp directory.
            max_batch_size (int): Max items per Gmail API batch request. Maximum 100 (Gmail API limit). Defaults to 10.
            instructions (Optional[str]): Custom instructions for the toolkit. If None, uses DEFAULT_INSTRUCTIONS.
            add_instructions (bool): Whether to inject toolkit instructions into the agent system prompt. Defaults to True.
        """
        if instructions is None:
            self.instructions = GMAIL_QUERY_INSTRUCTIONS
        else:
            self.instructions = instructions

        self.creds = creds
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service_account_path = service_account_path
        self.delegated_user = delegated_user
        self.service = None
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.port = port
        self.login_hint = login_hint
        self.include_html = include_html
        self.max_body_length = max_body_length
        self.attachment_dir = attachment_dir
        # Gmail API allows max 100 items per batch request
        self.max_batch_size = max(min(max_batch_size, 100), 1)
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._label_cache: Optional[Dict[str, str]] = None
        tools: List[Any] = []
        # Reading emails
        if get_latest_emails:
            tools.append(self.get_latest_emails)
        if get_emails_from_user:
            tools.append(self.get_emails_from_user)
        if get_unread_emails:
            tools.append(self.get_unread_emails)
        if get_starred_emails:
            tools.append(self.get_starred_emails)
        if get_emails_by_context:
            tools.append(self.get_emails_by_context)
        if get_emails_by_date:
            tools.append(self.get_emails_by_date)
        if get_emails_by_thread:
            tools.append(self.get_emails_by_thread)
        if search_emails:
            tools.append(self.search_emails)
        # Email management
        if mark_email_as_read:
            tools.append(self.mark_email_as_read)
        if mark_email_as_unread:
            tools.append(self.mark_email_as_unread)
        if star_email:
            tools.append(self.star_email)
        if unstar_email:
            tools.append(self.unstar_email)
        if archive_email:
            tools.append(self.archive_email)
        # Composing emails
        if create_draft_email:
            tools.append(self.create_draft_email)
        if send_email:
            tools.append(self.send_email)
        if send_email_reply:
            tools.append(self.send_email_reply)
        # Label management
        if list_custom_labels:
            tools.append(self.list_custom_labels)
        if apply_label:
            tools.append(self.apply_label)
        if remove_label:
            tools.append(self.remove_label)
        if delete_custom_label:
            tools.append(self.delete_custom_label)
        # Thread & message tools
        if get_message:
            tools.append(self.get_message)
        if get_thread:
            tools.append(self.get_thread)
        if search_threads:
            tools.append(self.search_threads)
        if modify_thread_labels:
            tools.append(self.modify_thread_labels)
        if trash_thread:
            tools.append(self.trash_thread)
        if get_draft:
            tools.append(self.get_draft)
        if list_drafts:
            tools.append(self.list_drafts)
        if send_draft:
            tools.append(self.send_draft)
        if update_draft:
            tools.append(self.update_draft)
        if list_labels:
            tools.append(self.list_labels)
        if modify_message_labels:
            tools.append(self.modify_message_labels)
        if trash_message:
            tools.append(self.trash_message)
        if download_attachment:
            tools.append(self.download_attachment)

        super().__init__(
            name="gmail_tools",
            tools=tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        # Validate that required scopes are present for requested operations (only check registered functions)
        compose_tools = {"create_draft_email", "send_email", "send_email_reply", "send_draft", "update_draft"}
        if any(t in self.functions for t in compose_tools):
            if "https://www.googleapis.com/auth/gmail.compose" not in self.scopes:
                raise ValueError(
                    "The scope https://www.googleapis.com/auth/gmail.compose is required for email composition operations"
                )

        read_operations = {
            "get_latest_emails",
            "get_emails_from_user",
            "get_unread_emails",
            "get_starred_emails",
            "get_emails_by_context",
            "get_emails_by_date",
            "get_emails_by_thread",
            "search_emails",
            "list_custom_labels",
            "get_message",
            "get_thread",
            "search_threads",
            "list_labels",
            "get_draft",
            "list_drafts",
            "download_attachment",
        }
        if any(op in self.functions for op in read_operations):
            read_scope = "https://www.googleapis.com/auth/gmail.readonly"
            write_scope = "https://www.googleapis.com/auth/gmail.modify"
            if read_scope not in self.scopes and write_scope not in self.scopes:
                raise ValueError(f"The scope {read_scope} is required for email reading operations")

        modify_operations = {
            "mark_email_as_read",
            "mark_email_as_unread",
            "star_email",
            "unstar_email",
            "archive_email",
            "apply_label",
            "remove_label",
            "delete_custom_label",
            "modify_message_labels",
            "modify_thread_labels",
            "trash_message",
            "trash_thread",
        }
        if any(op in self.functions for op in modify_operations):
            modify_scope = "https://www.googleapis.com/auth/gmail.modify"
            if modify_scope not in self.scopes:
                raise ValueError(f"The scope {modify_scope} is required for email modification operations")

    def _build_service(self):
        return build("gmail", "v1", credentials=self.creds)

    def _auth(self) -> None:
        """Authenticate with Gmail API using service account (priority) or OAuth flow."""
        if self.creds and self.creds.valid:
            return

        # Service account authentication takes priority over OAuth
        service_account_path = self.service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_account_path:
            delegated_user = self.delegated_user or getenv("GOOGLE_DELEGATED_USER")
            if not delegated_user:
                raise ValueError(
                    "delegated_user is required for Gmail service account authentication. "
                    "Gmail service accounts must impersonate a user via domain-wide delegation. "
                    "Provide delegated_user as a parameter or set GOOGLE_DELEGATED_USER env var."
                )
            self.creds = ServiceAccountCredentials.from_service_account_file(
                service_account_path,
                scopes=self.scopes,
                subject=delegated_user,
            )
            # Eagerly fetch token so creds.valid=True and @authenticate won't re-enter _auth
            self.creds.refresh(Request())
            return

        # OAuth flow
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                # Token file missing refresh_token — fall through to re-auth
                self.creds = None

        if self.creds and self.creds.expired and self.creds.refresh_token:  # type: ignore[union-attr]
            try:
                self.creds.refresh(Request())
            except Exception:
                # Refresh token revoked or expired — fall through to re-auth
                self.creds = None

        if not self.creds or not self.creds.valid:
            client_config = {
                "installed": {
                    "client_id": getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": getenv("GOOGLE_CLIENT_SECRET"),
                    "project_id": getenv("GOOGLE_PROJECT_ID"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [getenv("GOOGLE_REDIRECT_URI", "http://localhost")],
                }
            }
            if creds_file.exists():
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
            else:
                flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
            # prompt=consent forces Google to return a refresh_token every time
            oauth_kwargs: Dict[str, Any] = {"prompt": "consent"}
            if self.login_hint:
                oauth_kwargs["login_hint"] = self.login_hint
            self.creds = flow.run_local_server(port=self.port, **oauth_kwargs)

        # Save the credentials for future use
        if self.creds and self.creds.valid:
            token_file.write_text(self.creds.to_json())  # type: ignore[union-attr]
            log_debug("Gmail credentials saved")

    def _format_emails(self, emails: List[dict]) -> str:
        """Format list of email dictionaries into a readable string"""
        if not emails:
            return "No emails found"

        formatted_emails = []
        for email in emails:
            formatted_email = (
                f"From: {email['from']}\n"
                f"Subject: {email['subject']}\n"
                f"Date: {email['date']}\n"
                f"Body: {email['body']}\n"
                f"Message ID: {email['id']}\n"
                f"In-Reply-To: {email['in-reply-to']}\n"
                f"References: {email['references']}\n"
                f"Thread ID: {email['thread_id']}\n"
                "----------------------------------------"
            )
            formatted_emails.append(formatted_email)

        return "\n\n".join(formatted_emails)

    @authenticate
    def get_latest_emails(self, count: int) -> str:
        """
        Get the latest X emails from the user's inbox.

        Args:
            count (int): Number of latest emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving latest emails: {error}"
        except Exception as error:
            return f"Unexpected error retrieving latest emails: {type(error).__name__}: {error}"

    @authenticate
    def get_emails_from_user(self, user: str, count: int) -> str:
        """
        Get X number of emails from a specific user (name or email).

        Args:
            user (str): Name or email address of the sender
            count (int): Maximum number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            query = f"from:{user}" if "@" in user else f"from:{user}*"
            results = self.service.users().messages().list(userId="me", q=query, maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails from {user}: {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails from {user}: {type(error).__name__}: {error}"

    @authenticate
    def get_unread_emails(self, count: int) -> str:
        """
        Get the X number of latest unread emails from the user's inbox.

        Args:
            count (int): Maximum number of unread emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", q="is:unread", maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving unread emails: {error}"
        except Exception as error:
            return f"Unexpected error retrieving unread emails: {type(error).__name__}: {error}"

    @authenticate
    def get_emails_by_thread(self, thread_id: str) -> str:
        """
        Retrieve all emails from a specific thread.

        Args:
            thread_id (str): The ID of the email thread.

        Returns:
            str: Formatted string containing email thread details.
        """
        try:
            thread = self.service.users().threads().get(userId="me", id=thread_id).execute()  # type: ignore
            messages = thread.get("messages", [])
            emails = self._get_message_details(messages)
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails from thread {thread_id}: {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails from thread {thread_id}: {type(error).__name__}: {error}"

    @authenticate
    def get_starred_emails(self, count: int) -> str:
        """
        Get X number of starred emails from the user's inbox.

        Args:
            count (int): Maximum number of starred emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", q="is:starred", maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving starred emails: {error}"
        except Exception as error:
            return f"Unexpected error retrieving starred emails: {type(error).__name__}: {error}"

    @authenticate
    def get_emails_by_context(self, context: str, count: int) -> str:
        """
        Get X number of emails matching a specific context or search term.

        Args:
            context (str): Search term or context to match in emails
            count (int): Maximum number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", q=context, maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails by context '{context}': {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails by context '{context}': {type(error).__name__}: {error}"

    @authenticate
    def get_emails_by_date(
        self, start_date: str, range_in_days: Optional[int] = None, num_emails: Optional[int] = 10
    ) -> str:
        """Get emails from a date or date range.

        Args:
            start_date (str): Start date in YYYY/MM/DD format (e.g. "2026/03/01").
            range_in_days (Optional[int]): Number of days to include in the range (default: None, meaning all emails after start_date).
            num_emails (Optional[int]): Maximum number of emails to retrieve (default: 10).

        Returns:
            str: Formatted string containing email details.
        """
        try:
            start_date_dt = datetime.strptime(start_date, "%Y/%m/%d")
            if range_in_days:
                end_date = start_date_dt + timedelta(days=range_in_days)
                query = f"after:{start_date} before:{end_date.strftime('%Y/%m/%d')}"
            else:
                query = f"after:{start_date}"

            results = self.service.users().messages().list(userId="me", q=query, maxResults=num_emails).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails by date: {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails by date: {type(error).__name__}: {error}"

    @authenticate
    def create_draft_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> str:
        """
        Create and save a draft email. To reply to a thread, provide thread_id and message_id.
        to, cc and bcc are comma separated string of email ids.

        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)
            bcc (Optional[str]): Comma separated string of BCC email addresses (optional)
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)
            thread_id (Optional[str]): Thread ID to reply to (optional, makes this a reply draft)
            message_id (Optional[str]): Message ID being replied to (optional, used with thread_id)

        Returns:
            str: Stringified dictionary containing draft email details including id
        """
        try:
            self._validate_email_params(to, subject, body)

            # Process attachments
            attachment_files = []
            if attachments:
                if isinstance(attachments, str):
                    attachment_files = [attachments]
                else:
                    attachment_files = attachments

                for file_path in attachment_files:
                    if not Path(file_path).exists():
                        return f"Error: Attachment file not found: {file_path}"

            if thread_id and not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            message = self._create_message(
                to.split(","),
                subject,
                body,
                cc.split(",") if cc else None,
                bcc=bcc.split(",") if bcc else None,
                thread_id=thread_id,
                message_id=message_id,
                attachments=attachment_files,
            )
            draft = {"message": message}
            draft = self.service.users().drafts().create(userId="me", body=draft).execute()  # type: ignore
            return json.dumps(draft)
        except HttpError as error:
            return f"HTTP Error creating draft: {error}"
        except Exception as error:
            return f"Error creating draft: {type(error).__name__}: {error}"

    @authenticate
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> str:
        """
        Send an email immediately. To reply to a thread, provide thread_id and message_id.
        to, cc and bcc are comma separated string of email ids.

        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)
            bcc (Optional[str]): Comma separated string of BCC email addresses (optional)
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)
            thread_id (Optional[str]): Thread ID to reply to (optional, makes this a reply)
            message_id (Optional[str]): Message ID being replied to (optional, used with thread_id)

        Returns:
            str: Stringified dictionary containing sent email details including id
        """
        try:
            self._validate_email_params(to, subject, body)

            # Process attachments
            attachment_files = []
            if attachments:
                if isinstance(attachments, str):
                    attachment_files = [attachments]
                else:
                    attachment_files = attachments

                for file_path in attachment_files:
                    if not Path(file_path).exists():
                        return f"Error: Attachment file not found: {file_path}"

            if thread_id and not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            message = self._create_message(
                to.split(","),
                subject,
                body,
                cc.split(",") if cc else None,
                bcc=bcc.split(",") if bcc else None,
                thread_id=thread_id,
                message_id=message_id,
                attachments=attachment_files,
            )
            message = self.service.users().messages().send(userId="me", body=message).execute()  # type: ignore
            return json.dumps(message)
        except HttpError as error:
            return f"HTTP Error sending email: {error}"
        except Exception as error:
            return f"Error sending email: {type(error).__name__}: {error}"

    @authenticate
    def send_email_reply(
        self,
        thread_id: str,
        message_id: str,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
    ) -> str:
        """
        Respond to an existing email thread.

        Args:
            thread_id (str): The ID of the email thread to reply to.
            message_id (str): The ID of the email being replied to.
            to (str): Comma-separated recipient email addresses.
            subject (str): Email subject (prefixed with "Re:" if not already).
            body (str): Email body content.
            cc (Optional[str]): Comma-separated CC email addresses (optional).
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)

        Returns:
            str: Stringified dictionary containing sent email details including id.
        """
        try:
            self._validate_email_params(to, subject, body)

            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            # Process attachments
            attachment_files = []
            if attachments:
                if isinstance(attachments, str):
                    attachment_files = [attachments]
                else:
                    attachment_files = attachments

                for file_path in attachment_files:
                    if not Path(file_path).exists():
                        return f"Error: Attachment file not found: {file_path}"

            message = self._create_message(
                to.split(","),
                subject,
                body,
                cc=cc.split(",") if cc else None,
                thread_id=thread_id,
                message_id=message_id,
                attachments=attachment_files,
            )
            message = self.service.users().messages().send(userId="me", body=message).execute()  # type: ignore
            return json.dumps(message)
        except HttpError as error:
            return f"HTTP Error sending reply: {error}"
        except Exception as error:
            return f"Error sending reply: {type(error).__name__}: {error}"

    @authenticate
    def search_emails(self, query: str, count: int) -> str:
        """
        Get X number of emails based on a given natural text query.
        Searches in to, from, cc, subject and email body contents.

        Args:
            query (str): Natural language query to search for
            count (int): Number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            results = self.service.users().messages().list(userId="me", q=query, maxResults=count).execute()  # type: ignore
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except HttpError as error:
            return f"Error retrieving emails with query '{query}': {error}"
        except Exception as error:
            return f"Unexpected error retrieving emails with query '{query}': {type(error).__name__}: {error}"

    @authenticate
    def mark_email_as_read(self, message_id: str) -> str:
        """
        Mark a specific email as read by removing the 'UNREAD' label.
        This is crucial for long polling scenarios to prevent processing the same email multiple times.

        Args:
            message_id (str): The ID of the message to mark as read

        Returns:
            str: Success message or error description
        """
        try:
            # Remove the UNREAD label to mark the email as read
            modify_request = {"removeLabelIds": ["UNREAD"]}

            self.service.users().messages().modify(userId="me", id=message_id, body=modify_request).execute()  # type: ignore

            return f"Successfully marked email {message_id} as read. Labels removed: UNREAD"

        except HttpError as error:
            return f"HTTP Error marking email {message_id} as read: {error}"
        except Exception as error:
            return f"Error marking email {message_id} as read: {type(error).__name__}: {error}"

    @authenticate
    def mark_email_as_unread(self, message_id: str) -> str:
        """
        Mark a specific email as unread by adding the 'UNREAD' label.
        This is useful for flagging emails that need attention or re-processing.

        Args:
            message_id (str): The ID of the message to mark as unread

        Returns:
            str: Success message or error description
        """
        try:
            # Add the UNREAD label to mark the email as unread
            modify_request = {"addLabelIds": ["UNREAD"]}

            self.service.users().messages().modify(userId="me", id=message_id, body=modify_request).execute()  # type: ignore

            return f"Successfully marked email {message_id} as unread. Labels added: UNREAD"

        except HttpError as error:
            return f"HTTP Error marking email {message_id} as unread: {error}"
        except Exception as error:
            return f"Error marking email {message_id} as unread: {type(error).__name__}: {error}"

    @authenticate
    def star_email(self, message_id: str) -> str:
        """Add a star to an email message.

        Args:
            message_id (str): The ID of the message to star.

        Returns:
            str: Success message or error description.
        """
        try:
            modify_request = {"addLabelIds": ["STARRED"]}
            self.service.users().messages().modify(userId="me", id=message_id, body=modify_request).execute()  # type: ignore
            return f"Successfully starred email {message_id}"
        except HttpError as error:
            return f"HTTP Error starring email {message_id}: {error}"
        except Exception as error:
            return f"Error starring email {message_id}: {type(error).__name__}: {error}"

    @authenticate
    def unstar_email(self, message_id: str) -> str:
        """Remove the star from an email message.

        Args:
            message_id (str): The ID of the message to unstar.

        Returns:
            str: Success message or error description.
        """
        try:
            modify_request = {"removeLabelIds": ["STARRED"]}
            self.service.users().messages().modify(userId="me", id=message_id, body=modify_request).execute()  # type: ignore
            return f"Successfully unstarred email {message_id}"
        except HttpError as error:
            return f"HTTP Error unstarring email {message_id}: {error}"
        except Exception as error:
            return f"Error unstarring email {message_id}: {type(error).__name__}: {error}"

    @authenticate
    def archive_email(self, message_id: str) -> str:
        """Archive an email by removing it from the inbox. The email is NOT deleted and can still be found via search.

        Args:
            message_id (str): The ID of the message to archive.

        Returns:
            str: Success message or error description.
        """
        try:
            modify_request = {"removeLabelIds": ["INBOX"]}
            self.service.users().messages().modify(userId="me", id=message_id, body=modify_request).execute()  # type: ignore
            return f"Successfully archived email {message_id}"
        except HttpError as error:
            return f"HTTP Error archiving email {message_id}: {error}"
        except Exception as error:
            return f"Error archiving email {message_id}: {type(error).__name__}: {error}"

    @authenticate
    def list_custom_labels(self) -> str:
        """
        List only user-created custom labels (filters out system labels) in a numbered format.

        Returns:
            str: A numbered list of custom labels only
        """
        try:
            results = self.service.users().labels().list(userId="me").execute()  # type: ignore
            labels = results.get("labels", [])

            # Filter out only user-created labels
            custom_labels = [label["name"] for label in labels if label.get("type") == "user"]

            if not custom_labels:
                return "No custom labels found.\nCreate labels using apply_label function!"

            # Create numbered list
            numbered_labels = [f"{i}. {name}" for i, name in enumerate(custom_labels, 1)]
            return f"Your Custom Labels ({len(custom_labels)} total):\n\n" + "\n".join(numbered_labels)

        except HttpError as e:
            return f"Error fetching labels: {e}"
        except Exception as e:
            return f"Unexpected error: {type(e).__name__}: {e}"

    @authenticate
    def apply_label(self, context: str, label_name: str, count: int = 10) -> str:
        """
        Find emails matching a context (search query) and apply a label, creating it if necessary.

        Args:
            context (str): Gmail search query (e.g., 'is:unread category:promotions')
            label_name (str): Name of the label to apply
            count (int): Maximum number of emails to process
        Returns:
            str: Summary of labeled emails
        """
        try:
            # Fetch messages matching context
            results = self.service.users().messages().list(userId="me", q=context, maxResults=count).execute()  # type: ignore

            messages = results.get("messages", [])
            if not messages:
                return f"No emails found matching: '{context}'"

            # Populate cache if needed, then check existence
            self._resolve_label_ids([label_name])
            label_id = self._label_cache.get(label_name.lower())  # type: ignore[union-attr]
            if not label_id:
                label = (
                    self.service.users()  # type: ignore
                    .labels()
                    .create(
                        userId="me",
                        body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
                    )
                    .execute()
                )
                label_id = label["id"]
                # New label created — invalidate cache
                self._label_cache = None

            # Apply label to all matching messages
            for msg in messages:
                self.service.users().messages().modify(  # type: ignore
                    userId="me", id=msg["id"], body={"addLabelIds": [label_id]}
                ).execute()  # type: ignore

            return f"Applied label '{label_name}' to {len(messages)} emails matching '{context}'."

        except HttpError as e:
            return f"Error applying label '{label_name}': {e}"
        except Exception as e:
            return f"Unexpected error: {type(e).__name__}: {e}"

    @authenticate
    def remove_label(self, context: str, label_name: str, count: int = 10) -> str:
        """
        Remove a label from emails matching a context (search query).

        Args:
            context (str): Gmail search query (e.g., 'is:unread category:promotions')
            label_name (str): Name of the label to remove
            count (int): Maximum number of emails to process
        Returns:
            str: Summary of emails with label removed
        """
        try:
            # Populate cache if needed, then check existence
            self._resolve_label_ids([label_name])
            label_id = self._label_cache.get(label_name.lower())  # type: ignore[union-attr]
            if not label_id:
                return f"Label '{label_name}' not found."

            # Fetch messages matching context that have this label
            results = (
                self.service.users()  # type: ignore
                .messages()
                .list(userId="me", q=f"{context} label:{label_name}", maxResults=count)
                .execute()
            )

            messages = results.get("messages", [])
            if not messages:
                return f"No emails found matching: '{context}' with label '{label_name}'"

            # Remove label from all matching messages
            removed_count = 0
            for msg in messages:
                self.service.users().messages().modify(  # type: ignore
                    userId="me", id=msg["id"], body={"removeLabelIds": [label_id]}
                ).execute()  # type: ignore
                removed_count += 1

            return f"Removed label '{label_name}' from {removed_count} emails matching '{context}'."

        except HttpError as e:
            return f"Error removing label '{label_name}': {e}"
        except Exception as e:
            return f"Unexpected error: {type(e).__name__}: {e}"

    @authenticate
    def delete_custom_label(self, label_name: str, confirm: bool = False) -> str:
        """
        Delete a custom label (with safety confirmation).

        Args:
            label_name (str): Name of the label to delete
            confirm (bool): Must be True to actually delete the label
        Returns:
            str: Confirmation message or warning
        """
        if not confirm:
            return f"LABEL DELETION REQUIRES CONFIRMATION. This will permanently delete the label '{label_name}' from all emails. Set confirm=True to proceed."

        try:
            # Get all labels to find the target label
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
            target_label = None

            for label in labels:
                if label["name"].lower() == label_name.lower():
                    target_label = label
                    break

            if not target_label:
                return f"Label '{label_name}' not found."

            # Check if it's a system label using the type field
            if target_label.get("type") != "user":
                return f"Cannot delete system label '{label_name}'. Only user-created labels can be deleted."

            # Delete the label
            self.service.users().labels().delete(userId="me", id=target_label["id"]).execute()  # type: ignore
            self._label_cache = None

            return f"Successfully deleted label '{label_name}'. This label has been removed from all emails."

        except HttpError as e:
            return f"Error deleting label '{label_name}': {e}"
        except Exception as e:
            return f"Unexpected error: {type(e).__name__}: {e}"

    def _validate_email_params(self, to: str, subject: str, body: str) -> None:
        """Validate email parameters."""
        if not to:
            raise ValueError("Recipient email cannot be empty")

        # Validate each email in the comma-separated list
        for email in to.split(","):
            if not validate_email(email.strip()):
                raise ValueError(f"Invalid recipient email format: {email}")

        if not subject or not subject.strip():
            raise ValueError("Subject cannot be empty")

        if body is None:
            raise ValueError("Email body cannot be None")

    def _create_message(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> dict:
        """Build a base64-encoded MIME message dict ready for the Gmail API send/draft endpoints."""
        body = body.replace("\\n", "\n").replace("\n", "<br>")

        # Create multipart message if attachments exist, otherwise simple text message
        message: Union[MIMEMultipart, MIMEText]
        if attachments:
            message = MIMEMultipart()

            # Add the text body
            text_part = MIMEText(body, "html")
            message.attach(text_part)

            # Add attachments
            for file_path in attachments:
                file_path_obj = Path(file_path)
                if not file_path_obj.exists():
                    continue

                # Guess the content type based on the file extension
                content_type, encoding = mimetypes.guess_type(file_path)
                if content_type is None or encoding is not None:
                    content_type = "application/octet-stream"

                _, sub_type = content_type.split("/", 1)

                # Read file and create attachment
                with open(file_path, "rb") as file:
                    attachment_data = file.read()

                attachment = MIMEApplication(attachment_data, _subtype=sub_type)
                attachment.add_header("Content-Disposition", "attachment", filename=file_path_obj.name)
                message.attach(attachment)
        else:
            message = MIMEText(body, "html")

        # Set headers
        message["to"] = ", ".join(to)
        message["from"] = "me"
        message["subject"] = subject

        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)

        # Add reply headers if this is a response
        if thread_id and message_id:
            message["In-Reply-To"] = message_id
            message["References"] = message_id

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        email_data = {"raw": raw_message}

        if thread_id:
            email_data["threadId"] = thread_id

        return email_data

    def _get_message_details(self, messages: List[dict]) -> List[dict]:
        """Get details for list of messages"""
        details = []
        for msg in messages:
            msg_data = self.service.users().messages().get(userId="me", id=msg["id"], format="full").execute()  # type: ignore
            details.append(
                {
                    "id": msg_data["id"],
                    "thread_id": msg_data.get("threadId"),
                    "subject": next(
                        (header["value"] for header in msg_data["payload"]["headers"] if header["name"] == "Subject"),
                        None,
                    ),
                    "from": next(
                        (header["value"] for header in msg_data["payload"]["headers"] if header["name"] == "From"), None
                    ),
                    "date": next(
                        (header["value"] for header in msg_data["payload"]["headers"] if header["name"] == "Date"), None
                    ),
                    "in-reply-to": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"] == "In-Reply-To"
                        ),
                        None,
                    ),
                    "references": next(
                        (
                            header["value"]
                            for header in msg_data["payload"]["headers"]
                            if header["name"] == "References"
                        ),
                        None,
                    ),
                    "body": self._get_message_body(msg_data),
                }
            )
        return details

    def _get_message_body(self, msg_data: dict) -> str:
        """Extract message body from message data"""
        body = ""
        attachments = []
        try:
            if "parts" in msg_data["payload"]:
                for part in msg_data["payload"]["parts"]:
                    if part["mimeType"] == "text/plain":
                        if "data" in part["body"]:
                            body = base64.urlsafe_b64decode(part["body"]["data"]).decode()
                    elif "filename" in part:
                        attachments.append(part["filename"])
            elif "body" in msg_data["payload"] and "data" in msg_data["payload"]["body"]:
                body = base64.urlsafe_b64decode(msg_data["payload"]["body"]["data"]).decode()
        except Exception:
            return "Unable to decode message body"

        if attachments:
            return f"{body}\n\nAttachments: {', '.join(attachments)}"
        return body

    def _decode_body_data(self, data: str) -> str:
        """Decode a base64url-encoded Gmail body part to text."""
        try:
            raw_bytes = base64.urlsafe_b64decode(data)
        except Exception:
            return ""
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1")

    def _resolve_label_ids(self, label_names: List[str]) -> List[str]:
        """Convert label names to Gmail label IDs. Falls back to raw name for system labels like INBOX."""
        if self._label_cache is None:
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
            self._label_cache = {lbl["name"].lower(): lbl["id"] for lbl in labels}
        return [self._label_cache.get(name.lower(), name) for name in label_names]

    def _batch_get(
        self,
        ids: List[str],
        request_builder: Callable,
    ) -> List[Dict]:
        """Execute multiple Gmail API requests in batched HTTP calls.

        Args:
            ids: List of resource IDs to fetch.
            request_builder: Callable that takes an ID and returns a Gmail API request object.

        Returns:
            List of API response dicts (or error dicts for failed requests).
        """
        service = self.service
        results: List[Dict] = []

        def callback(request_id: str, response: Any, exception: Any) -> None:
            if exception:
                log_error(f"Batch request {request_id} failed: {exception}")
                results.append({"id": request_id, "error": str(exception)})
            else:
                results.append(response)

        for i in range(0, len(ids), self.max_batch_size):
            chunk = ids[i : i + self.max_batch_size]
            batch = service.new_batch_http_request(callback=callback)  # type: ignore
            for item_id in chunk:
                batch.add(request_builder(item_id), request_id=item_id)
            batch.execute()
        return results

    def _download_attachment_file(self, message_id: str, attachment_id: str, filename: str) -> str:
        """Download a Gmail attachment to disk and return the local file path."""
        service = self.service
        att = (
            service.users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()  # type: ignore
        )
        data = base64.urlsafe_b64decode(att["data"])
        if self.attachment_dir:
            dest_dir = Path(self.attachment_dir)
        else:
            if self._temp_dir is None:
                self._temp_dir = tempfile.TemporaryDirectory()
            dest_dir = Path(self._temp_dir.name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Strip directory components to prevent path traversal from sender-controlled filenames
        safe_name = Path(filename).name or "attachment"
        file_path = dest_dir / safe_name
        file_path.write_bytes(data)
        log_debug(f"Downloaded attachment: {file_path}")
        return str(file_path)

    def _format_message(self, msg_data: Dict, include_body: bool = True) -> Dict[str, Any]:
        """Convert a raw Gmail API message into a clean dict with id, subject, from, to, date, body, and attachments."""
        raw_headers = msg_data.get("payload", {}).get("headers", [])
        headers = {h["name"].lower(): h["value"] for h in raw_headers}
        result: Dict[str, Any] = {
            "id": msg_data["id"],
            "threadId": msg_data.get("threadId"),
            "labelIds": msg_data.get("labelIds", []),
            "snippet": msg_data.get("snippet", ""),
            "subject": headers.get("subject"),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "date": headers.get("date"),
            "cc": headers.get("cc"),
            "inReplyTo": headers.get("in-reply-to"),
            "references": headers.get("references"),
        }
        if include_body and "payload" in msg_data:
            body, attachments = self._extract_body(msg_data["payload"])
            result["body"] = body
            if attachments:
                result["attachments"] = attachments
        return result

    def _extract_body(self, payload: Dict) -> Tuple[str, List[Dict]]:
        """Extract text body and attachment metadata from a Gmail message payload.

        Handles multipart MIME, prefers text/plain over text/html, strips HTML tags
        unless include_html is set, and truncates to max_body_length.

        Returns:
            Tuple of (body_text, list_of_attachment_dicts).
        """
        mime_type = payload.get("mimeType", "")

        if "parts" not in payload:
            data = payload.get("body", {}).get("data")
            if not data:
                return "", []
            text = self._decode_body_data(data)
            if "html" in mime_type and not self.include_html:
                text = re.sub(r"<[^>]+>", "", text)
                text = "\n".join(s for s in (line.strip() for line in text.splitlines()) if s)
            if self.max_body_length and len(text) > self.max_body_length:
                text = text[: self.max_body_length] + "... [truncated]"
            return text, []

        plain_parts: List[str] = []
        html_parts: List[str] = []
        attachments: List[Dict] = []

        for part in payload["parts"]:
            part_mime = part.get("mimeType", "")

            if part_mime.startswith("multipart/"):
                sub_body, sub_att = self._extract_body(part)
                if sub_body:
                    plain_parts.append(sub_body)
                attachments.extend(sub_att)
                continue

            part_body = part.get("body", {})
            if part_body.get("attachmentId"):
                attachments.append(
                    {
                        "filename": part.get("filename", "unknown"),
                        "mimeType": part_mime,
                        "size": part_body.get("size", 0),
                        "attachmentId": part_body["attachmentId"],
                    }
                )
                continue

            data = part_body.get("data")
            if not data:
                continue

            if part_mime == "text/plain":
                plain_parts.append(self._decode_body_data(data))
            elif part_mime == "text/html":
                html_parts.append(self._decode_body_data(data))

        if plain_parts:
            body = "\n".join(plain_parts)
        elif html_parts:
            html = "\n".join(html_parts)
            if self.include_html:
                body = html
            else:
                body = re.sub(r"<[^>]+>", "", html)
                body = "\n".join(s for s in (line.strip() for line in body.splitlines()) if s)
        else:
            body = ""

        if self.max_body_length and len(body) > self.max_body_length:
            body = body[: self.max_body_length] + "... [truncated]"
        return body, attachments

    # -- New tools ----------------------------------------------------------------

    @authenticate
    def get_message(self, message_id: str, download_attachments: bool = False) -> str:
        """Get a single email message by its ID with full content including headers, body, and attachment metadata.

        Args:
            message_id: The Gmail message ID.
            download_attachments: If True, download attachments to disk and include file paths in the response.

        Returns:
            JSON string with message content including id, threadId, subject, from, to, date, body, and attachments.
        """
        try:
            service = self.service
            raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()  # type: ignore
            result = self._format_message(raw)
            if download_attachments and result.get("attachments"):
                for att in result["attachments"]:
                    if att.get("attachmentId"):
                        att["localPath"] = self._download_attachment_file(
                            message_id, att["attachmentId"], att["filename"]
                        )
            return json.dumps(result)
        except HttpError as e:
            log_error(f"Failed to get message {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def get_thread(self, thread_id: str) -> str:
        """Get all messages in a Gmail thread as structured JSON.

        Args:
            thread_id: The Gmail thread ID.

        Returns:
            JSON string with thread metadata and all messages in chronological order.
        """
        try:
            service = self.service
            thread = service.users().threads().get(userId="me", id=thread_id).execute()  # type: ignore
            messages = [self._format_message(m) for m in thread.get("messages", [])]
            return json.dumps(
                {
                    "threadId": thread_id,
                    "messages": messages,
                    "messageCount": len(messages),
                }
            )
        except HttpError as e:
            log_error(f"Failed to get thread {thread_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def search_threads(self, query: str, count: int = 10) -> str:
        """Search Gmail threads using Gmail query syntax. Returns thread IDs and snippets, not full message content.

        Args:
            query: Gmail search query string. Supports all Gmail operators like from:, to:, subject:, is:unread, etc.
            count: Maximum number of threads to return (default 10, max 500).

        Returns:
            JSON string with list of matching threads with their IDs and snippets.
        """
        try:
            service = self.service
            max_results = min(count, 500)
            results = service.users().threads().list(userId="me", q=query, maxResults=max_results).execute()  # type: ignore
            threads = results.get("threads", [])
            return json.dumps(
                {
                    "threads": threads,
                    "resultSizeEstimate": results.get("resultSizeEstimate", len(threads)),
                }
            )
        except HttpError as e:
            log_error(f"Thread search failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def modify_thread_labels(
        self,
        thread_id: str,
        add_labels: Optional[str] = None,
        remove_labels: Optional[str] = None,
    ) -> str:
        """Add or remove labels from an entire thread (all messages in the conversation).

        Args:
            thread_id: The Gmail thread ID.
            add_labels: Comma-separated label names to add (e.g. 'STARRED,Important').
            remove_labels: Comma-separated label names to remove (e.g. 'UNREAD,INBOX').

        Returns:
            JSON string with updated thread label state.
        """
        try:
            body: Dict[str, List[str]] = {}
            if add_labels:
                names = [n.strip() for n in add_labels.split(",") if n.strip()]
                body["addLabelIds"] = self._resolve_label_ids(names)
            if remove_labels:
                names = [n.strip() for n in remove_labels.split(",") if n.strip()]
                body["removeLabelIds"] = self._resolve_label_ids(names)

            if not body:
                return json.dumps({"error": "Must specify add_labels or remove_labels"})

            service = self.service
            result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()  # type: ignore
            return json.dumps({"threadId": result["id"], "labelIds": result.get("labelIds", [])})
        except HttpError as e:
            log_error(f"Failed to modify labels on thread {thread_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def trash_thread(self, thread_id: str) -> str:
        """Move an entire thread to the trash. All messages in the conversation will be trashed.

        Args:
            thread_id: The Gmail thread ID to trash.

        Returns:
            JSON string confirming the thread was trashed.
        """
        try:
            service = self.service
            service.users().threads().trash(userId="me", id=thread_id).execute()  # type: ignore
            return json.dumps({"threadId": thread_id, "action": "trashed"})
        except HttpError as e:
            log_error(f"Failed to trash thread {thread_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def get_draft(self, draft_id: str) -> str:
        """Get a draft email by its ID with full message content.

        Args:
            draft_id: The Gmail draft ID.

        Returns:
            JSON string with draft ID and full message details.
        """
        try:
            service = self.service
            draft = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()  # type: ignore
            msg_data = draft.get("message", {})
            return json.dumps(
                {
                    "draftId": draft["id"],
                    "message": self._format_message(msg_data) if msg_data else {},
                }
            )
        except HttpError as e:
            log_error(f"Failed to get draft {draft_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def list_drafts(self, count: int = 10) -> str:
        """List draft emails in the mailbox.

        Args:
            count: Maximum number of drafts to return (default 10, max 500).

        Returns:
            JSON string with list of draft IDs and estimated total count.
        """
        try:
            service = self.service
            max_results = min(count, 500)
            results = service.users().drafts().list(userId="me", maxResults=max_results).execute()  # type: ignore
            drafts = results.get("drafts", [])
            return json.dumps({"drafts": drafts, "resultSizeEstimate": results.get("resultSizeEstimate", len(drafts))})
        except HttpError as e:
            log_error(f"Failed to list drafts: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def send_draft(self, draft_id: str) -> str:
        """Send an existing draft email.

        Args:
            draft_id: The Gmail draft ID to send.

        Returns:
            JSON string with sent message ID, thread ID, and labels.
        """
        try:
            service = self.service
            result = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()  # type: ignore
            return json.dumps(
                {
                    "id": result.get("id"),
                    "threadId": result.get("threadId"),
                    "labelIds": result.get("labelIds", []),
                }
            )
        except HttpError as e:
            log_error(f"Failed to send draft {draft_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def update_draft(
        self,
        draft_id: str,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> str:
        """Replace the content of an existing draft email.

        Args:
            draft_id: The Gmail draft ID to update.
            to: Comma-separated recipient email addresses.
            subject: Email subject line.
            body: Email body content.
            cc: Comma-separated CC email addresses (optional).
            bcc: Comma-separated BCC email addresses (optional).
            attachments: File path(s) for attachments (optional).
            thread_id: Thread ID for reply drafts (optional).
            message_id: Message ID being replied to, used with thread_id (optional).

        Returns:
            JSON string with updated draft ID.
        """
        try:
            self._validate_email_params(to, subject, body)
            attachment_files: List[str] = []
            if attachments:
                attachment_files = [attachments] if isinstance(attachments, str) else list(attachments)
                for fp in attachment_files:
                    p = Path(fp)
                    try:
                        size = p.stat().st_size
                    except FileNotFoundError:
                        raise ValueError(f"Attachment file not found: {fp}")
                    if size > 25 * 1024 * 1024:
                        raise ValueError(f"Attachment exceeds 25MB limit: {fp}")

            if thread_id and not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            mime = self._create_message(
                to=[t.strip() for t in to.split(",")],
                subject=subject,
                body=body,
                cc=[c.strip() for c in cc.split(",")] if cc else None,
                bcc=[b.strip() for b in bcc.split(",")] if bcc else None,
                thread_id=thread_id,
                message_id=message_id,
                attachments=attachment_files or None,
            )

            service = self.service
            result = service.users().drafts().update(userId="me", id=draft_id, body={"message": mime}).execute()  # type: ignore
            return json.dumps({"draftId": result["id"]})
        except HttpError as e:
            log_error(f"Failed to update draft {draft_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Failed to update draft {draft_id}: {e}")
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    @authenticate
    def list_labels(self) -> str:
        """List all Gmail labels (system and custom) with message and thread counts.

        Returns:
            JSON string with list of label objects including name, type, and message/thread counts.
        """
        try:
            service = self.service
            results = service.users().labels().list(userId="me").execute()  # type: ignore
            labels = results.get("labels", [])

            label_ids = [lbl["id"] for lbl in labels]
            detailed_labels = self._batch_get(label_ids, lambda lid: service.users().labels().get(userId="me", id=lid))  # type: ignore
            formatted = []
            for detail in detailed_labels:
                if "error" in detail:
                    continue
                formatted.append(
                    {
                        "id": detail["id"],
                        "name": detail["name"],
                        "type": detail.get("type", "system"),
                        "messagesTotal": detail.get("messagesTotal", 0),
                        "messagesUnread": detail.get("messagesUnread", 0),
                        "threadsTotal": detail.get("threadsTotal", 0),
                        "threadsUnread": detail.get("threadsUnread", 0),
                    }
                )
            return json.dumps({"labels": formatted, "count": len(formatted)})
        except HttpError as e:
            log_error(f"Failed to list labels: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def modify_message_labels(
        self,
        message_id: str,
        add_labels: Optional[str] = None,
        remove_labels: Optional[str] = None,
    ) -> str:
        """Add or remove labels from a single message. Use for marking read/unread, starring, categorizing, etc.
        For example: add_labels="STARRED" or remove_labels="UNREAD" to mark as read.

        Args:
            message_id: The Gmail message ID.
            add_labels: Comma-separated label names to add (e.g. 'STARRED,Work').
            remove_labels: Comma-separated label names to remove (e.g. 'UNREAD,INBOX').

        Returns:
            JSON string with updated message label state.
        """
        try:
            body: Dict[str, List[str]] = {}
            if add_labels:
                names = [n.strip() for n in add_labels.split(",") if n.strip()]
                body["addLabelIds"] = self._resolve_label_ids(names)
            if remove_labels:
                names = [n.strip() for n in remove_labels.split(",") if n.strip()]
                body["removeLabelIds"] = self._resolve_label_ids(names)

            if not body:
                return json.dumps({"error": "Must specify add_labels or remove_labels"})

            service = self.service
            result = service.users().messages().modify(userId="me", id=message_id, body=body).execute()  # type: ignore
            return json.dumps({"id": result["id"], "labelIds": result.get("labelIds", [])})
        except HttpError as e:
            log_error(f"Failed to modify labels on message {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def trash_message(self, message_id: str, undo: bool = False) -> str:
        """Move a message to trash, or restore it from trash with undo=True.

        Args:
            message_id: The Gmail message ID.
            undo: If True, restore the message from trash instead of trashing it.

        Returns:
            JSON string confirming the action.
        """
        try:
            service = self.service
            if undo:
                service.users().messages().untrash(userId="me", id=message_id).execute()  # type: ignore
                return json.dumps({"id": message_id, "action": "untrashed"})
            else:
                service.users().messages().trash(userId="me", id=message_id).execute()  # type: ignore
                return json.dumps({"id": message_id, "action": "trashed"})
        except HttpError as e:
            action_name = "untrash" if undo else "trash"
            log_error(f"Failed to {action_name} message {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    @authenticate
    def download_attachment(self, message_id: str, attachment_id: str, filename: str) -> str:
        """Download an email attachment to disk. Use get_message first to find attachment IDs.

        Args:
            message_id: The Gmail message ID containing the attachment.
            attachment_id: The attachment ID from the message's attachment metadata.
            filename: The filename to save the attachment as.

        Returns:
            JSON string with the local file path where the attachment was saved.
        """
        try:
            local_path = self._download_attachment_file(message_id, attachment_id, filename)
            return json.dumps({"localPath": local_path, "filename": filename, "messageId": message_id})
        except HttpError as e:
            log_error(f"Failed to download attachment from {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except Exception as e:
            log_error(f"Unexpected error: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})
