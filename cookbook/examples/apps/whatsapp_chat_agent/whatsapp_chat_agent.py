import logging
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.whatsapp import WhatsAppTools
from agno.tools.yfinance import YFinanceTools
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configure constants
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
if not VERIFY_TOKEN:
    raise ValueError("WHATSAPP_VERIFY_TOKEN must be set in .envrc")

WEBHOOK_URL = os.getenv("WHATSAPP_WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WHATSAPP_WEBHOOK_URL must be set in .envrc")

AGENT_STORAGE_FILE = "tmp/whatsapp_agents.db"

# Initialize WhatsApp tools and agent
whatsapp = WhatsAppTools()
agent = Agent(
    name="WhatsApp Assistant",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        whatsapp,
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            stock_fundamentals=True,
            historical_prices=True,
            company_info=True,
            company_news=True,
        ),
    ],
    storage=SqliteAgentStorage(table_name="whatsapp_agent", db_file=AGENT_STORAGE_FILE),
    add_history_to_messages=True,
    num_history_responses=3,
    markdown=True,
    description="You are a financial advisor and can help with stock-related queries. You will respond like how people talk to each other on whatsapp, with short sentences and simple language. don't add markdown to your responses.",
)

# Create FastAPI app
app = FastAPI()


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Handle WhatsApp webhook verification"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    logger.info(f"Webhook verification request - Mode: {mode}, Token: {token}")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        if not challenge:
            raise HTTPException(status_code=400, detail="No challenge received")
        return PlainTextResponse(content=challenge)

    raise HTTPException(status_code=403, detail="Invalid verify token or mode")


@app.post("/webhook")
async def handle_message(request: Request):
    """Handle incoming WhatsApp messages"""
    try:
        body = await request.json()

        # Validate webhook data
        if body.get("object") != "whatsapp_business_account":
            logger.warning(
                f"Received non-WhatsApp webhook object: {body.get('object')}"
            )
            return {"status": "ignored"}

        # Process messages
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])

                if not messages:
                    continue

                message = messages[0]
                if message.get("type") != "text":
                    continue

                # Extract message details
                phone_number = message["from"]
                message_text = message["text"]["body"]

                logger.info(f"Processing message from {phone_number}: {message_text}")

                # Generate and send response
                response = agent.run(message_text)
                whatsapp.send_text_message_sync(
                    recipient=phone_number, text=response.content
                )
                logger.info(f"Response sent to {phone_number}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting WhatsApp Bot Server")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    logger.info(f"Verify Token: {VERIFY_TOKEN}")
    logger.info(
        "Make sure your .env file contains WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)
