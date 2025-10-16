from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import json
from typing import Optional
from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from .gmail_tools import GmailTools
from agno.utils.log import log_error, log_info
from agno.app.email.gmail.setup import extract_emails
# Scopes and token file

SCOPES = [
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]
TOKEN_FILE = 'token.json'

def get_gmail_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    return build('gmail', 'v1', credentials=creds)
def get_async_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()
    @router.post("/gmail")
    async def gmail_webhook(request: Request):
        body = await request.json()
        raw_data = body.get("message", {}).get("data")

        if not raw_data:
            return {"error": "No data in message"}

        try:
            # Decode base64 message
            decoded_bytes = base64.urlsafe_b64decode(raw_data)
            decoded_str = decoded_bytes.decode('utf-8')
            payload = json.loads(decoded_str)

            receipent_email = payload.get("emailAddress")
            history_id = payload.get("historyId")
            log_info(f" Notification for {receipent_email}, historyId: {history_id}")
            
            email_message =GmailTools.get_latest_emails(1)
            if len(email_message) < 1:
                log_info("No email message found")
                print(agent.run_response({"message": "No email message found"}))
            log_info(f"Email message: {email_message}")
            
            extracted_emails = extract_emails(email_message)
            log_info(f"Emails: {extracted_emails}")
            #from_email = extracted_emails
        # Skip if the email is from our own agent
            '''
            if from_email == receipent_email:
                log_info("Skipping email from our own agent")
                print(agent.run_response({"message": "Skipped email from agent"}))
            '''
        except Exception as e:
            log_error(" Failed to decode or process:", e)
        return {"status": "ok"}
    return router