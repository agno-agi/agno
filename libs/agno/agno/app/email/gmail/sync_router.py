from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import json
from typing import Optional
from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team


# Scopes and token file
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_FILE = 'token.json'

# Store the last known history ID (in real apps use DB or file)
LAST_HISTORY_FILE = 'last_history.json'

def get_gmail_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    return build('gmail', 'v1', credentials=creds)
def get_sync_router(agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    router = APIRouter()
    @router.post("/gmail")
    def gmail_webhook(request: Request):
        body = request.json()
        raw_data = body.get("message", {}).get("data")

        if not raw_data:
            return {"error": "No data in message"}

        try:
            # Decode base64 message
            decoded_bytes = base64.urlsafe_b64decode(raw_data)
            decoded_str = decoded_bytes.decode('utf-8')
            payload = json.loads(decoded_str)

            email = payload.get("emailAddress")
            history_id = payload.get("historyId")

            print(f"📩 Notification for {email}, historyId: {history_id}")
            print(decoded_bytes,"\n",decoded_str)
            # Continue as before — fetch new messages from history
            
            
        except Exception as e:
            print("❌ Failed to decode or process:", e)
            return {"error": "Failed to decode"}

        return {"status": "ok"}
