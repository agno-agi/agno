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

5. Set up environment variables:
   Create a .envrc file in your project root with:
   ```
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://localhost  # Default value
   ```

Note: The first time you run the application, it will open a browser window for OAuth authentication.
A token.json file will be created to store the authentication credentials for future use.
"""

import base64
import re
from datetime import datetime, timedelta
from functools import wraps
from os import getenv
from pathlib import Path
from typing import List, Optional

from agno.tools import Toolkit

try:
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


def authenticate(func):
    """Decorator to ensure authentication before executing a function."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.creds or not self.creds.valid:
            self._auth()
        if not self.service:
            self.service = build("gmail", "v1", credentials=self.creds)
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
        get_latest_emails: bool = True,
        get_emails_from_user: bool = True,
        get_unread_emails: bool = True,
        get_starred_emails: bool = True,
        get_emails_by_context: bool = True,
        get_emails_by_date: bool = True,
        get_emails_by_thread: bool = True,
        create_draft_email: bool = True,
        send_email: bool = True,
        send_email_reply: bool = True,
        search_emails: bool = True,
        creds: Optional[Credentials] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ):
        """Initialize GmailTools and authenticate with Gmail API

        Args:
            get_latest_emails (bool): Enable getting latest emails. Defaults to True.
            get_emails_from_user (bool): Enable getting emails from specific user. Defaults to True.
            get_unread_emails (bool): Enable getting unread emails. Defaults to True.
            get_starred_emails (bool): Enable getting starred emails. Defaults to True.
            get_emails_by_context (bool): Enable getting emails by context. Defaults to True.
            get_emails_by_date (bool): Enable getting emails by date. Defaults to True.
            get_emails_by_thread (bool): Enable getting emails by thread. Defaults to True.
            create_draft_email (bool): Enable creating draft emails. Defaults to True.
            send_email (bool): Enable sending emails. Defaults to True.
            search_emails (bool): Enable searching emails. Defaults to True.
            send_email_reply (bool): Enable sending email replies. Defaults to True.
            creds (Optional[Credentials]): Pre-existing credentials. Defaults to None.
            credentials_path (Optional[str]): Path to credentials file. Defaults to None.
            token_path (Optional[str]): Path to token file. Defaults to None.
            scopes (Optional[List[str]]): Custom OAuth scopes. If None, uses DEFAULT_SCOPES.
        """
        super().__init__(name="gmail_tools")
        self.creds = creds
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.scopes = scopes or self.DEFAULT_SCOPES

        # Validate that required scopes are present for requested operations
        if (create_draft_email or send_email) and "https://www.googleapis.com/auth/gmail.compose" not in self.scopes:
            raise ValueError(
                "The scope https://www.googleapis.com/auth/gmail.compose is required for email composition operations"
            )

        read_operations = [
            get_latest_emails,
            get_emails_from_user,
            get_unread_emails,
            get_starred_emails,
            get_emails_by_context,
            get_emails_by_date,
            get_emails_by_thread,
            search_emails,
        ]

        if any(read_operations):
            read_scope = "https://www.googleapis.com/auth/gmail.readonly"
            write_scope = "https://www.googleapis.com/auth/gmail.modify"
            if read_scope not in self.scopes and write_scope not in self.scopes:
                raise ValueError(f"The scope {read_scope} is required for email reading operations")

        if get_latest_emails:
            self.register(self.get_latest_emails)
        if get_emails_from_user:
            self.register(self.get_emails_from_user)
        if get_unread_emails:
            self.register(self.get_unread_emails)
        if get_starred_emails:
            self.register(self.get_starred_emails)
        if get_emails_by_context:
            self.register(self.get_emails_by_context)
        if get_emails_by_date:
            self.register(self.get_emails_by_date)
        if get_emails_by_thread:
            self.register(self.get_emails_by_thread)
        if create_draft_email:
            self.register(self.create_draft_email)
        if send_email:
            self.register(self.send_email)
        if send_email_reply:
            self.register(self.send_email_reply)
        if search_emails:
            self.register(self.search_emails)

    def _auth(self) -> None:
        """Authenticate with Gmail API"""
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
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
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for future use
            if self.creds and self.creds.valid:
                token_file.write_text(self.creds.to_json())

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
    def create_draft_email(self, to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
        """
        Create and save a draft email. to and cc are comma separated string of email ids
        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)

        Returns:
            str: Stringified dictionary containing draft email details including id
        """
        self._validate_email_params(to, subject, body)
        message = self._create_message(to.split(","), subject, body, cc.split(",") if cc else None)
        draft = {"message": message}
        draft = self.service.users().drafts().create(userId="me", body=draft).execute()  # type: ignore
        return str(draft)

    @authenticate
    def send_email(self, to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
        """
        Send an email immediately. to and cc are comma separated string of email ids
        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)

        Returns:
            str: Stringified dictionary containing sent email details including id
        """
        self._validate_email_params(to, subject, body)
        body = body.replace("\n", "<br>")
        message = self._create_message(to.split(","), subject, body, cc.split(",") if cc else None)
        message = self.service.users().messages().send(userId="me", body=message).execute()  # type: ignore
        return str(message)

    @authenticate
    def send_email_reply(
        self, thread_id: str, message_id: str, to: str, subject: str, body: str, cc: Optional[str] = None
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

        Returns:
            str: Stringified dictionary containing sent email details including id.
        """
        self._validate_email_params(to, subject, body)

        # Ensure subject starts with "Re:" for consistency
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body = body.replace("\n", "<br>")
        message = self._create_message(
            to.split(","), subject, body, cc.split(",") if cc else None, thread_id, message_id
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
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> dict:
        body = body.replace("\\n", "\n")
        message = MIMEText(body, "html")
        message["to"] = ", ".join(to)
        message["from"] = "me"
        message["subject"] = subject

        if cc:
            message["Cc"] = ", ".join(cc)

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
