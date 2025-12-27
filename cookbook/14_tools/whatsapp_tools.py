"""
WhatsApp Cookbook
----------------

This cookbook demonstrates how to use WhatsApp integration with Agno. Before running this example,
you'll need to complete these setup steps:

1. Create Meta Developer Account
   - Go to [Meta Developer Portal](https://developers.facebook.com/) and create a new account
   - Create a new app at [Meta Apps Dashboard](https://developers.facebook.com/apps/)
   - Enable WhatsApp integration for your app [here](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)

2. Set Up WhatsApp Business API
   You can get your WhatsApp Business Account ID from [Business Settings](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)

3. Configure Environment
   - Set these environment variables:
     WHATSAPP_ACCESS_TOKEN=your_access_token          # Access Token
     WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id    # Phone Number ID
     WHATSAPP_RECIPIENT_WAID=your_recipient_waid      # Recipient WhatsApp ID (e.g. 1234567890)
     WHATSAPP_VERSION=your_whatsapp_version           # WhatsApp API Version (e.g. v22.0)

Important Notes:
- For first-time outreach, you must use pre-approved message templates
  [here](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates)
- Test messages can only be sent to numbers that are registered in your test environment

The example below shows how to send a template message using Agno's WhatsApp tools.
For more complex use cases, check out the WhatsApp Cloud API documentation:
[here](https://developers.facebook.com/docs/whatsapp/cloud-api/overview)
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.whatsapp import WhatsAppTools

agent = Agent(
    name="whatsapp",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[WhatsAppTools()],
)

# Example: Send a template message
# Note: Replace 'hello_world' with your actual template name
agent.print_response(
    "Send a template message using the 'hello_world' template in English to +1 123456789"
)
