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
"""

import base64
import json
import mimetypes
import re
import tempfile
from datetime import datetime, timedelta
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client library for Python not found , install it using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


_BATCH_MAX = 100


def authenticate(func):
    """Decorator to ensure authentication before executing a function."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            if not self.creds or not self.creds.valid:
                self._auth()
            if not self.service:
                self.service = build("gmail", "v1", credentials=self.creds)
        except Exception as e:
            return json.dumps({"error": f"Gmail authentication failed: {e}"})
        return func(self, *args, **kwargs)

    return wrapper


def validate_email(email: str) -> bool:
    """Validate email format."""
    email = email.strip()
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


class GmailTools(Toolkit):
    # Default scopes for Gmail API access
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]

    def __init__(
        self,
        creds: Optional[Credentials] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
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
        # Composing
        create_draft_email: bool = True,
        send_email: bool = True,
        send_email_reply: bool = True,
        # Labels
        list_custom_labels: bool = True,
        apply_label: bool = True,
        remove_label: bool = True,
        delete_custom_label: bool = True,
        # New tools (opt-in, default False)
        get_message: bool = False,
        get_messages_batch: bool = False,
        get_profile: bool = False,
        get_thread: bool = False,
        search_threads: bool = False,
        get_threads_batch: bool = False,
        modify_thread_labels: bool = False,
        trash_thread: bool = False,
        draft_email: bool = False,
        list_labels: bool = False,
        modify_labels: bool = False,
        batch_modify_labels: bool = False,
        manage_label: bool = False,
        trash_message: bool = False,
        download_attachment: bool = False,
        **kwargs,
    ):
        """Initialize GmailTools and authenticate with Gmail API

        Args:
            creds (Optional[Credentials]): Pre-fetched OAuth credentials. Use this to skip a new auth flow. Defaults to None.
            credentials_path (Optional[str]): Path to credentials file. Defaults to None.
            token_path (Optional[str]): Path to token file. Defaults to None.
            scopes (Optional[List[str]]): Custom OAuth scopes. If None, uses DEFAULT_SCOPES.
            port (Optional[int]): Port to use for OAuth authentication. Defaults to None.
            login_hint (Optional[str]): Email to pre-select in the OAuth consent screen. Defaults to None.
            include_html (bool): If True, return raw HTML body instead of stripping tags. Defaults to False.
            max_body_length (Optional[int]): Truncate message bodies to this length. Defaults to None (no truncation).
            attachment_dir (Optional[str]): Directory to save downloaded attachments. Defaults to a temp directory.
        """
        self.creds = creds
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.port = port
        self.login_hint = login_hint
        self.include_html = include_html
        self.max_body_length = max_body_length
        self.attachment_dir = attachment_dir
        self._temp_dir: Optional[str] = None

        # When include_tools is specified, expose the full catalog and let
        # Toolkit's whitelist filter select the requested tools.
        if kwargs.get("include_tools"):
            tools = self._all_tools()
        else:
            tools: List[Any] = []  # type: ignore
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
            # New tools
            if get_message:
                tools.append(self.get_message)
            if get_messages_batch:
                tools.append(self.get_messages_batch)
            if get_profile:
                tools.append(self.get_profile)
            if get_thread:
                tools.append(self.get_thread)
            if search_threads:
                tools.append(self.search_threads)
            if get_threads_batch:
                tools.append(self.get_threads_batch)
            if modify_thread_labels:
                tools.append(self.modify_thread_labels)
            if trash_thread:
                tools.append(self.trash_thread)
            if draft_email:
                tools.append(self.draft_email)
            if list_labels:
                tools.append(self.list_labels)
            if modify_labels:
                tools.append(self.modify_labels)
            if batch_modify_labels:
                tools.append(self.batch_modify_labels)
            if manage_label:
                tools.append(self.manage_label)
            if trash_message:
                tools.append(self.trash_message)
            if download_attachment:
                tools.append(self.download_attachment)

        super().__init__(name="gmail_tools", tools=tools, **kwargs)

        # Validate that required scopes are present for requested operations (only check registered functions)
        compose_tools = {"create_draft_email", "send_email", "send_email_reply", "draft_email"}
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
            "get_messages_batch",
            "get_thread",
            "search_threads",
            "get_threads_batch",
            "list_labels",
            "get_profile",
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
            "apply_label",
            "remove_label",
            "delete_custom_label",
            "modify_labels",
            "batch_modify_labels",
            "modify_thread_labels",
            "manage_label",
            "trash_message",
            "trash_thread",
        }
        if any(op in self.functions for op in modify_operations):
            modify_scope = "https://www.googleapis.com/auth/gmail.modify"
            if modify_scope not in self.scopes:
                raise ValueError(f"The scope {modify_scope} is required for email modification operations")

    def _all_tools(self) -> list:
        return [
            self.get_latest_emails,
            self.get_emails_from_user,
            self.get_unread_emails,
            self.get_starred_emails,
            self.get_emails_by_context,
            self.get_emails_by_date,
            self.get_emails_by_thread,
            self.search_emails,
            self.send_email,
            self.send_email_reply,
            self.create_draft_email,
            self.mark_email_as_read,
            self.mark_email_as_unread,
            self.list_custom_labels,
            self.apply_label,
            self.remove_label,
            self.delete_custom_label,
            self.get_message,
            self.get_messages_batch,
            self.get_profile,
            self.get_thread,
            self.search_threads,
            self.get_threads_batch,
            self.modify_thread_labels,
            self.trash_thread,
            self.draft_email,
            self.list_labels,
            self.modify_labels,
            self.batch_modify_labels,
            self.manage_label,
            self.trash_message,
            self.download_attachment,
        ]

    def _auth(self) -> None:
        """Authenticate with Gmail API"""
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                # Token file missing refresh_token — fall through to re-auth
                self.creds = None

        if self.creds and self.creds.expired and self.creds.refresh_token:
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

        if self.creds and self.creds.valid:
            token_file.write_text(self.creds.to_json())
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
        self, start_date: int, range_in_days: Optional[int] = None, num_emails: Optional[int] = 10
    ) -> str:
        """
        Get emails based on date range. start_date is an integer representing a unix timestamp

        Args:
            start_date (datetime): Start date for the query
            range_in_days (Optional[int]): Number of days to include in the range (default: None)
            num_emails (Optional[int]): Maximum number of emails to retrieve (default: 10)

        Returns:
            str: Formatted string containing email details
        """
        try:
            start_date_dt = datetime.fromtimestamp(start_date)
            if range_in_days:
                end_date = start_date_dt + timedelta(days=range_in_days)
                query = f"after:{start_date_dt.strftime('%Y/%m/%d')} before:{end_date.strftime('%Y/%m/%d')}"
            else:
                query = f"after:{start_date_dt.strftime('%Y/%m/%d')}"

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
        attachments: Optional[Union[str, List[str]]] = None,
    ) -> str:
        """
        Create and save a draft email. to and cc are comma separated string of email ids
        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)

        Returns:
            str: Stringified dictionary containing draft email details including id
        """
        self._validate_email_params(to, subject, body)

        # Process attachments
        attachment_files = []
        if attachments:
            if isinstance(attachments, str):
                attachment_files = [attachments]
            else:
                attachment_files = attachments

            # Validate attachment files
            for file_path in attachment_files:
                if not Path(file_path).exists():
                    raise ValueError(f"Attachment file not found: {file_path}")

        message = self._create_message(
            to.split(","), subject, body, cc.split(",") if cc else None, attachments=attachment_files
        )
        draft = {"message": message}
        draft = self.service.users().drafts().create(userId="me", body=draft).execute()  # type: ignore
        return str(draft)

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
        self._validate_email_params(to, subject, body)

        # Process attachments
        attachment_files = []
        if attachments:
            if isinstance(attachments, str):
                attachment_files = [attachments]
            else:
                attachment_files = attachments

            # Validate attachment files
            for file_path in attachment_files:
                if not Path(file_path).exists():
                    raise ValueError(f"Attachment file not found: {file_path}")

        if thread_id and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body = body.replace("\n", "<br>")
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
        return str(message)

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
        self._validate_email_params(to, subject, body)

        # Ensure subject starts with "Re:" for consistency
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Process attachments
        attachment_files = []
        if attachments:
            if isinstance(attachments, str):
                attachment_files = [attachments]
            else:
                attachment_files = attachments

            # Validate attachment files
            for file_path in attachment_files:
                if not Path(file_path).exists():
                    raise ValueError(f"Attachment file not found: {file_path}")

        body = body.replace("\n", "<br>")
        message = self._create_message(
            to.split(","),
            subject,
            body,
            cc.split(",") if cc else None,
            thread_id,  # type: ignore
            message_id,
            attachments=attachment_files,
        )
        message = self.service.users().messages().send(userId="me", body=message).execute()  # type: ignore
        return str(message)

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

            # Check if label exists, create if not
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
            label_id = None
            for label in labels:
                if label["name"].lower() == label_name.lower():
                    label_id = label["id"]
                    break

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
            # Get all labels to find the target label
            labels = self.service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
            label_id = None

            for label in labels:
                if label["name"].lower() == label_name.lower():
                    label_id = label["id"]
                    break

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
        body = body.replace("\\n", "\n")

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

                main_type, sub_type = content_type.split("/", 1)

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
        try:
            raw_bytes = base64.urlsafe_b64decode(data)
        except Exception:
            return ""
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1")

    def _resolve_label_ids(self, label_names: List[str]) -> List[str]:
        service = self.service
        labels = service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
        lookup = {lbl["name"].lower(): lbl["id"] for lbl in labels}
        # Fall back to the raw name (allows system label IDs like INBOX, UNREAD)
        return [lookup.get(name.lower(), name) for name in label_names]

    def _batch_get(
        self,
        ids: List[str],
        request_builder: Callable,
    ) -> List[Dict]:
        service = self.service
        results: List[Dict] = []

        def callback(request_id: str, response: Any, exception: Any) -> None:
            if exception:
                log_error(f"Batch request {request_id} failed: {exception}")
                results.append({"id": request_id, "error": str(exception)})
            else:
                results.append(response)

        for i in range(0, len(ids), _BATCH_MAX):
            chunk = ids[i : i + _BATCH_MAX]
            batch = service.new_batch_http_request(callback=callback)  # type: ignore
            for item_id in chunk:
                batch.add(request_builder(item_id), request_id=item_id)
            batch.execute()
        return results

    def _download_attachment_file(self, message_id: str, attachment_id: str, filename: str) -> str:
        service = self.service
        att = (
            service.users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()  # type: ignore
        )
        data = base64.urlsafe_b64decode(att["data"])
        if self.attachment_dir:
            dest_dir = Path(self.attachment_dir)
        else:
            if self._temp_dir is None:
                self._temp_dir = tempfile.mkdtemp()
            dest_dir = Path(self._temp_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = dest_dir / filename
        file_path.write_bytes(data)
        log_debug(f"Downloaded attachment: {file_path}")
        return str(file_path)

    def _format_message(self, msg_data: Dict, include_body: bool = True) -> Dict[str, Any]:
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

    @authenticate
    def get_messages_batch(self, message_ids: str, download_attachments: bool = False) -> str:
        """Get multiple email messages by their IDs in a single batch request. Much faster than fetching one at a time.

        Args:
            message_ids: Comma-separated list of Gmail message IDs (max 100).
            download_attachments: If True, download attachments to disk.

        Returns:
            JSON string with list of messages.
        """
        try:
            ids = [mid.strip() for mid in message_ids.split(",") if mid.strip()]
            if len(ids) > _BATCH_MAX:
                return json.dumps({"error": f"Maximum {_BATCH_MAX} messages per batch request"})

            service = self.service
            raw_messages = self._batch_get(
                ids,
                lambda msg_id: service.users().messages().get(userId="me", id=msg_id, format="full"),  # type: ignore
            )
            messages = []
            for m in raw_messages:
                if "error" in m:
                    messages.append(m)
                    continue
                formatted = self._format_message(m)
                if download_attachments and formatted.get("attachments"):
                    for att in formatted["attachments"]:
                        if att.get("attachmentId"):
                            att["localPath"] = self._download_attachment_file(
                                m["id"], att["attachmentId"], att["filename"]
                            )
                messages.append(formatted)

            return json.dumps({"messages": messages})
        except HttpError as e:
            log_error(f"Batch get messages failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def get_profile(self) -> str:
        """Get the authenticated user's Gmail profile including email address, total messages, and history ID.

        Returns:
            JSON string with profile details: emailAddress, messagesTotal, threadsTotal, historyId.
        """
        try:
            service = self.service
            profile = service.users().getProfile(userId="me").execute()  # type: ignore
            return json.dumps(profile)
        except HttpError as e:
            log_error(f"Failed to get profile: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

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

    @authenticate
    def get_threads_batch(self, thread_ids: str) -> str:
        """Get multiple threads by their IDs in a single batch request. Each thread includes all its messages.

        Args:
            thread_ids: Comma-separated list of Gmail thread IDs (max 100).

        Returns:
            JSON string with list of threads, each containing all their messages.
        """
        try:
            ids = [tid.strip() for tid in thread_ids.split(",") if tid.strip()]
            if len(ids) > _BATCH_MAX:
                return json.dumps({"error": f"Maximum {_BATCH_MAX} threads per batch request"})

            service = self.service
            raw_threads = self._batch_get(ids, lambda tid: service.users().threads().get(userId="me", id=tid))  # type: ignore
            threads = []
            for t in raw_threads:
                if "error" in t:
                    threads.append(t)
                    continue
                messages = [self._format_message(m) for m in t.get("messages", [])]
                threads.append(
                    {
                        "threadId": t["id"],
                        "messages": messages,
                        "messageCount": len(messages),
                    }
                )
            return json.dumps({"threads": threads})
        except HttpError as e:
            log_error(f"Batch get threads failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

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

    @authenticate
    def draft_email(
        self,
        action: str,
        to: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
        draft_id: Optional[str] = None,
        count: int = 20,
    ) -> str:
        """Manage email drafts: create, update, send, get, or list.
        to, cc, and bcc are comma-separated email addresses.

        Args:
            action: One of "create", "update", "send", "get", "list".
            to: Comma-separated recipient emails (required for create/update).
            subject: Email subject (required for create/update).
            body: Email body content (required for create/update).
            cc: Comma-separated CC emails (optional, for create/update).
            bcc: Comma-separated BCC emails (optional, for create/update).
            attachments: File path(s) for attachments (optional, for create/update).
            draft_id: Draft ID (required for update, send, get).
            count: Maximum drafts to return for list action (default 20, max 500).

        Returns:
            JSON string with draft details or list of drafts.
        """
        try:
            service = self.service

            if action == "list":
                max_results = min(count, 500)
                results = service.users().drafts().list(userId="me", maxResults=max_results).execute()  # type: ignore
                drafts = results.get("drafts", [])
                return json.dumps(
                    {"drafts": drafts, "resultSizeEstimate": results.get("resultSizeEstimate", len(drafts))}
                )

            if action == "get":
                if not draft_id:
                    return json.dumps({"error": "draft_id is required for get action"})
                draft = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()  # type: ignore
                msg_data = draft.get("message", {})
                return json.dumps(
                    {
                        "draftId": draft["id"],
                        "message": self._format_message(msg_data) if msg_data else {},
                    }
                )

            if action == "send":
                if not draft_id:
                    return json.dumps({"error": "draft_id is required for send action"})
                result = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()  # type: ignore
                return json.dumps(
                    {
                        "id": result.get("id"),
                        "threadId": result.get("threadId"),
                        "labelIds": result.get("labelIds", []),
                        "action": "sent",
                    }
                )

            if action in ("create", "update"):
                if not to or not subject or body is None:
                    return json.dumps({"error": "to, subject, and body are required for create/update"})
                if action == "update" and not draft_id:
                    return json.dumps({"error": "draft_id is required for update action"})
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

                mime = self._create_message(
                    to=[t.strip() for t in to.split(",")],
                    subject=subject,
                    body=body.replace("\n", "<br>"),
                    cc=[c.strip() for c in cc.split(",")] if cc else None,
                    bcc=[b.strip() for b in bcc.split(",")] if bcc else None,
                    attachments=attachment_files or None,
                )

                if action == "update":
                    result = service.users().drafts().update(userId="me", id=draft_id, body={"message": mime}).execute()  # type: ignore
                    return json.dumps({"draftId": result["id"], "action": "updated"})
                else:
                    draft = service.users().drafts().create(userId="me", body={"message": mime}).execute()  # type: ignore
                    return json.dumps({"draftId": draft["id"], "action": "created"})

            return json.dumps({"error": f"Invalid action: {action}. Must be one of: create, update, send, get, list"})
        except HttpError as e:
            log_error(f"Draft operation '{action}' failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
        except ValueError as e:
            return json.dumps({"error": str(e)})

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

    @authenticate
    def modify_labels(
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

    @authenticate
    def batch_modify_labels(
        self,
        message_ids: str,
        add_labels: Optional[str] = None,
        remove_labels: Optional[str] = None,
    ) -> str:
        """Apply label changes to multiple messages at once. Much more efficient than modifying one at a time.

        Args:
            message_ids: Comma-separated list of Gmail message IDs (max 1000).
            add_labels: Comma-separated label names to add.
            remove_labels: Comma-separated label names to remove.

        Returns:
            JSON string confirming the batch operation.
        """
        try:
            ids = [mid.strip() for mid in message_ids.split(",") if mid.strip()]
            if len(ids) > 1000:
                return json.dumps({"error": "Maximum 1000 messages per batch modify"})

            body: Dict[str, Any] = {"ids": ids}
            if add_labels:
                names = [n.strip() for n in add_labels.split(",") if n.strip()]
                body["addLabelIds"] = self._resolve_label_ids(names)
            if remove_labels:
                names = [n.strip() for n in remove_labels.split(",") if n.strip()]
                body["removeLabelIds"] = self._resolve_label_ids(names)

            if "addLabelIds" not in body and "removeLabelIds" not in body:
                return json.dumps({"error": "Must specify add_labels or remove_labels"})

            service = self.service
            service.users().messages().batchModify(userId="me", body=body).execute()  # type: ignore
            return json.dumps(
                {
                    "modified": len(ids),
                    "addedLabels": body.get("addLabelIds", []),
                    "removedLabels": body.get("removeLabelIds", []),
                }
            )
        except HttpError as e:
            log_error(f"Batch modify labels failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def manage_label(
        self,
        action: str,
        name: str,
        new_name: Optional[str] = None,
        confirm: bool = False,
    ) -> str:
        """Create, rename, or delete a custom label.

        Args:
            action: One of "create", "rename", "delete".
            name: Label name (target label for all actions).
            new_name: New label name (required for rename).
            confirm: Must be True to delete (safety guard).

        Returns:
            JSON string with label operation result.
        """
        try:
            service = self.service

            if action == "create":
                label = (
                    service.users()  # type: ignore
                    .labels()
                    .create(
                        userId="me",
                        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
                    )
                    .execute()
                )
                return json.dumps({"id": label["id"], "name": label["name"], "action": "created"})

            if action == "rename":
                if not new_name:
                    return json.dumps({"error": "new_name is required for rename action"})
                labels = service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
                lower = name.lower()
                label_id = next((lbl["id"] for lbl in labels if lbl["name"].lower() == lower), None)
                if not label_id:
                    return json.dumps({"error": f"Label '{name}' not found"})
                result = service.users().labels().update(userId="me", id=label_id, body={"name": new_name}).execute()  # type: ignore
                return json.dumps({"id": result["id"], "name": result["name"], "action": "renamed"})

            if action == "delete":
                if not confirm:
                    return json.dumps(
                        {
                            "warning": f"This will permanently delete the label '{name}' from all emails.",
                            "action_required": "Set confirm=True to proceed.",
                        }
                    )
                labels = service.users().labels().list(userId="me").execute().get("labels", [])  # type: ignore
                lower = name.lower()
                target = None
                for label in labels:
                    if label["name"].lower() == lower:
                        target = label
                        break
                if not target:
                    return json.dumps({"error": f"Label '{name}' not found"})
                if target.get("type") != "user":
                    return json.dumps(
                        {"error": f"Cannot delete system label '{name}'. Only custom labels can be deleted."}
                    )
                service.users().labels().delete(userId="me", id=target["id"]).execute()  # type: ignore
                return json.dumps({"label": name, "action": "deleted"})

            return json.dumps({"error": f"Invalid action: {action}. Must be one of: create, rename, delete"})
        except HttpError as e:
            log_error(f"Label operation '{action}' failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

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
