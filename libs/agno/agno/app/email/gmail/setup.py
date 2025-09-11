from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
def get_gmail_service(cred_path):
    flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
    creds = flow.run_local_server(port=0) #add_the url of the port to redirect url
    service = build('gmail', 'v1', credentials=creds)
    return service

def setup_watch(service,topic_name):
    request_body = {
        'labelIds': ['INBOX'],
        'topicName': topic_name
    }
    response = service.users().watch(userId='me', body=request_body).execute()
    print("Watch set up. Response:", response)
def runsetup(topic_name,cred_path):
    service = get_gmail_service(cred_path)
    setup_watch(service,topic_name)

def extract_emails(email_data):
        """
        Extract email address from email data where subject contains 'siemens'.

        Args:
            email_data: Can be a single email dict or a list of email dicts

        Returns:
            str: Extracted email address, or None if no valid email found
        """
        if not email_data:
            return None

        # Convert single email to list for uniform processing
        emails_list = email_data if isinstance(email_data, list) else [email_data]

        for email in emails_list:
            # Extract from 'from' field if present
            if "from" in email:
                from_field = email["from"]
                extracted_email = from_field.split("<")[1].strip(">") if "<" in from_field else from_field
                if "@" in extracted_email:
                    return extracted_email

        return None
