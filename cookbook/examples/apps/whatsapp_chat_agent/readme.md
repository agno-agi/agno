# WhatsApp Business API Integration with AI Agent

This is a WhatsApp chatbot that automatically responds to incoming messages using an AI agent. The bot runs on FastAPI and uses the WhatsApp Business API to handle message interactions.

## Features

- Automatically responds to any incoming WhatsApp messages
- Uses AI to generate contextual responses
- Handles webhook verification for WhatsApp Business API
- Supports secure HTTPS communication
- Logs all interactions for monitoring

## Prerequisites

- Python 3.7+
- ngrok account (for development/testing)
- WhatsApp Business API access
- Meta Developer account
- OpenAI API key

## Getting WhatsApp Credentials

1. **Create Meta Developer Account**:

   - Go to [Meta Developer Portal](https://developers.facebook.com/) and create an account
   - Create a new app at [Meta Apps Dashboard](https://developers.facebook.com/apps/)
   - Enable WhatsApp integration for your app

2. **Set Up WhatsApp Business API**:

   - Go to your app's WhatsApp Setup page
   - Find your WhatsApp Business Account ID in Business Settings
   - Get your Phone Number ID from the WhatsApp > Getting Started page
   - Generate a permanent access token in App Dashboard > WhatsApp > API Setup

3. **Test Environment Setup**:
   - Note: Initially, you can only send messages to numbers registered in your test environment
   - For production, you'll need to submit your app for review

## Environment Setup

Create a `.envrc` file in the project root with these variables:

```bash
# From Meta Developer Portal
export WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token    # From App Dashboard > WhatsApp > API Setup
export WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id      # From WhatsApp > Getting Started
export WHATSAPP_WEBHOOK_URL=your_webhook_url              # Your ngrok URL + /webhook
export WHATSAPP_VERIFY_TOKEN=your_verify_token           # Any secure string you choose

# For OpenAI integration
export OPENAI_API_KEY=your_openai_api_key
```

## Installation

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set up your environment variables in `.envrc`:

```bash
source .envrc
```

## Running the Application

You need to run two components:

1. **The ngrok tunnel** (in one terminal):

```bash
ngrok http --domain=your-domain.ngrok-free.app 8000
```

2. **The FastAPI server** (in another terminal):

```bash
python app.py
```

## WhatsApp Business Setup

1. Go to Meta Developer Portal
2. Set up your WhatsApp Business account
3. Configure the webhook:
   - URL: Your ngrok URL + "/webhook" (e.g., https://your-domain.ngrok-free.app/webhook)
   - Verify Token: Same as WHATSAPP_VERIFY_TOKEN in your .envrc
   - Subscribe to the 'messages' webhook field

## How It Works

1. When someone sends a message to your WhatsApp Business number:

   - The message is received via webhook
   - The AI agent processes the message
   - A response is automatically generated and sent back

2. The agent can:
   - Process incoming text messages
   - Generate contextual responses
   - Log all interactions

## Monitoring

The application logs important events:

- Server start/stop
- Incoming messages
- Response generation
- Message delivery status

Check the console output for logs.

## Error Handling

The application includes error handling for:

- Invalid webhook verification
- Message processing errors
- API communication issues

## Security Notes

- Keep your environment variables secure
- Don't commit `.envrc` to version control
- Use HTTPS for all communications
- Regularly rotate your access tokens

## Troubleshooting

Common issues:

1. Webhook verification failing:

   - Check your VERIFY_TOKEN matches
   - Ensure ngrok is running
   - Verify webhook URL is correct

2. Messages not being received:

   - Check webhook subscription status
   - Verify WhatsApp Business API access

3. No responses being sent:
   - Verify OpenAI API key
   - Check WhatsApp access token

## Support

For issues and questions:

1. Check the logs for error messages
2. Review Meta's WhatsApp Business API documentation
3. Verify your API credentials and tokens
