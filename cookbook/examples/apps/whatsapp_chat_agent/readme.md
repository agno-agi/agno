# WhatsApp Chat Agent with Stock Market Insights

This is a WhatsApp chatbot that provides stock market insights and financial advice using the WhatsApp Business API. The bot is built using FastAPI and can be run locally using ngrok for development and testing.

## Prerequisites

- Python 3.7+
- ngrok account (free tier works fine)
- WhatsApp Business API access
- Meta Developer account
- OpenAI API key

## Setup Instructions

1. **Install Dependencies**

```bash
pip install -r requirements.txt
```

2. **Set up ngrok (for development testing only)**

   - Download and install ngrok from https://ngrok.com/download
   - Sign up for a free account and get your auth-token
   - Authenticate ngrok with your token:
     ```bash
     ngrok config add-authtoken YOUR_AUTH_TOKEN
     ```

3. **Create a Meta Developer Account**

   - Go to https://developers.facebook.com/
   - Create a new app
   - Set up WhatsApp in your app
   - Get your WhatsApp Business Account ID and Phone Number ID

4. **Environment Variables**
   Create a `.envrc` file in the project root with the following variables:

```bash
export WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token
export WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
export WHATSAPP_RECIPIENT_WAID=phone_number_with_country_code  # e.g. +1234567890
export WHATSAPP_WEBHOOK_URL=your_webhook_url
export WHATSAPP_VERIFY_TOKEN=your_custom_verify_token  # Can be any string you choose
export WHATSAPP_WEBHOOK_URL=your_webhook_url
export OPENAI_API_KEY=your_openai_api_key
```

## Running the Application

1. **Start the FastAPI server**

```bash
python app.py
```

2. **Start ngrok**
   In a new terminal window:

```bash
ngrok http 8000
```

3. **Configure Webhook**
   - Copy the HTTPS URL provided by ngrok (e.g., https://xxxx-xx-xx-xxx-xx.ngrok.io)
   - Go to your Meta Developer Portal
   - Set up Webhooks for your WhatsApp Business Account
   - Use the ngrok URL + "/webhook" as your Callback URL
   - Use your WHATSAPP_VERIFY_TOKEN as the Verify Token
   - Subscribe to the `messages` webhook

## Testing the Bot

1. Send a message to your WhatsApp Business number
2. The bot should respond with stock market insights based on your query
3. You can ask questions about:
   - Stock prices
   - Company information
   - Analyst recommendations
   - Stock fundamentals
   - Historical prices
   - Company news

## Troubleshooting

- Make sure all environment variables are properly set
- Check the FastAPI logs for any errors
- Verify that ngrok is running and the webhook URL is correctly configured
- Ensure your WhatsApp Business API is properly set up and the phone number is verified

## Important Notes

- The ngrok URL changes every time you restart ngrok, You can also use a static ngrok URL by running `ngrok http 8000 --domain=your-custom-domain.com`, you can get a custom domain from [here](https://dashboard.ngrok.com/domains)
- You'll need to update the Webhook URL in the Meta Developer Portal whenever the ngrok URL changes
- Keep your WHATSAPP_ACCESS_TOKEN and other credentials secure
- The bot stores conversation history in a SQLite database in the `tmp` directory
