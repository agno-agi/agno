"""
WhatsApp Cookbook
----------------

This cookbook demonstrates how to use WhatsApp integration with Agno. Before running this example,
you'll need to complete these setup steps:

1. Create Meta Developer Account
   - Go to Meta Developer Portal (https://developers.facebook.com/) and create a new account
   - Create a new app at Meta Apps Dashboard (https://developers.facebook.com/apps/)
   - Enable WhatsApp integration for your app (https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)

2. Set Up WhatsApp Business API
   - Get your WhatsApp Business Account ID from Business Settings (https://business.facebook.com/settings/)
   - Generate a permanent access token in System Users (https://business.facebook.com/settings/system-users)
   - Set up a test phone number (https://developers.facebook.com/docs/whatsapp/cloud-api/get-started#testing-your-app)
   - Create a message template in Meta Business Manager (https://business.facebook.com/wa/manage/message-templates/)

3. Configure Environment
   - Set these environment variables:
     WHATSAPP_ACCESS_TOKEN=your_access_token          # Permanent access token from System Users
     WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id    # Your WhatsApp test phone number ID

Important Notes:
- WhatsApp has a 24-hour messaging window policy
- You can only send free-form messages to users who have messaged you in the last 24 hours
- For first-time outreach, you must use pre-approved message templates
  (https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates)
- Test messages can only be sent to numbers that are registered in your test environment

The example below shows how to send a template message using Agno's WhatsApp tools.
For more complex use cases, check out the WhatsApp Cloud API documentation:
https://developers.facebook.com/docs/whatsapp/cloud-api/overview
"""

from agno.agent import Agent
from agno.tools.whatsapp import WhatsAppTools

agent = Agent(
    name="whatsapp",
    tools=[WhatsAppTools()],
)

# Example: Send a template message
# Note: Replace 'hello_world' with your actual template name
agent.print_response(
    "Send a template message using the 'hello_world' template in English"
)
