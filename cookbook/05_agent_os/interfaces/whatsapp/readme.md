
# WhatsApp API Module Documentation

## Overview
The WhatsApp API module provides integration between WhatsApp Business API and AI agents, allowing for automated message handling and responses through WhatsApp. The module is built on FastAPI and supports various agent configurations.

## Example Implementations
1. **Basic WhatsApp Agent** (`basic.py`)
   - Simple implementation with basic agent configuration
   - Uses GPT-4 model
   - Includes message history and datetime features

2. **Reasoning Agent** (`reasoning_agent.py`)
   - Uses Claude
   - Can reason about financial questions and write reports comparing companies

3.  **Media Agent** (`agent_with_media.py`)
   - Uses Gemini
   - Can analyse images and videos
   - Can respond to audio messages

4. **Image Generation Agent** (`image_generation_agent.py`)
   - Can generate images

5. **User Memory Agent** (`agent_with_user_memory.py`)
   - Enhanced implementation with persistent memory
   - Uses SQLite for storage
   - Captures and utilizes user information
   - Features:
     - User name collection
     - Hobbies and interests tracking
     - Personalized responses

6. **Study Friend Agent** (`study_friend.py`)
   - Specialized educational assistant
   - Features:
     - Memory-based learning
     - DuckDuckGo search integration
     - YouTube resource recommendations
     - Personalized study plans
     - Emotional support capabilities

7. **Image Agent** (`image_generation_model.py` & `image_generation_model.py`)
   - Image Generation implementations
   - Features:
     - Model Image generation through Gemini 2.0
     - Tool Image generation through OpenAI's GPT image generation

## Setup and Configuration

### Prerequisites
- Python 3.7+
- A Meta Developer Account
- A Meta Business Account
- A valid Facebook account
- ngrok (for development)

### Getting WhatsApp Credentials
1. **Create a Meta App**
	1.	Go to [Meta for Developers](https://developers.facebook.com/) and verify your account
   2. Create a new app at [Meta Apps Dashboard](https://developers.facebook.com/apps/)
   3. Under "Use Case", select "Other"
	4.	Choose "Business" as the app type
	5.	Provide:
	•	App name
	•	Contact email
	6.	Click Create App

2: **Set Up a Meta Business Account**
	1.	Navigate to [Meta Business Manager](https://business.facebook.com/).
	2.	Create a new business account or use an existing one.
   3. Verify your business by clicking on the email link.
	4. Go to your App page, go to "App settings / Basic" and click "Start Verification" under "Business Verification".  You'll have to complete the verification process for production.
   5. Associate the app with your business account and click Create App.

3. **Setup WhatsApp Business API**
   1. Go to your app's WhatsApp Setup page
   2. Click on "Start using the API" (API Setup).
   3. Generate a Access Token.
   4. Copy your Phone Number ID.
   5. Copy your WhatsApp Business Account ID.
   6. Add a "To" number that you will use for testing (probably your personal number).

4. **Setup environment variables**
   1. Create a `.envrc` file with:
   ```bash
   export WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token
   export WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
   export WHATSAPP_WEBHOOK_URL=your_webhook_url
   export WHATSAPP_VERIFY_TOKEN=your_verify_token

5. **Setup Webhook**
   1. For local testing with Agno's WhatsappApp and agents, we recommend using ngrok to create a secure tunnel to your local server. It is also easier if you get a static url from ngrok.
   2. Run ngrok:
   ```bash
   ngrok http --url=your-url.ngrok-free.app http://localhost:8000
   ```
   3. Click on "Configure a webhook".
   4. Configure the webhook:
      - URL: Your ngrok URL + "/whatsapp/webhook" (e.g., https://your-domain.ngrok-free.app/whatsapp/webhook) (or with a custom prefix: https://your-domain.ngrok-free.app/custom-prefix/webhook)
      - Verify Token: Same as WHATSAPP_VERIFY_TOKEN in your .envrc
   5. Run your app locally with `python <my-app>.py` and click "Verify and save".
   6. Subscribe to the 'messages' webhook field.
   
6. **Development Mode**
   1. `export APP_ENV=development`

7. **Production Mode** 
   1. `export APP_ENV=production`
   2. You need a secret to sign messages.`export WHATSAPP_APP_SECRET=any_secret_you_choose`

## Limitations
- Initially, you can only send messages to numbers registered in your test environment
- For production, you'll need to submit your app for review
- Messages are limited to 4096 characters. Messages are sent back in batches of 4096 characters.
- Whatsapp Business API cannot send messages to groups.

## Agent Configuration

### Basic Agent Setup
To create a basic agent, you'll need to:
1. Import the necessary components from the agno package
2. Configure your agent with:
   - A name
   - Your preferred model (e.g., OpenAI, Gemini, etc.)
   - Optional features like message history, datetime context, and markdown support
3. Create the WhatsApp API app instance with your agent

### Memory-Enabled Agent Setup
To create an agent with memory capabilities:
1. Set up a database for memory storage (SQLite is supported by default)
2. Configure the memory manager with your desired memory capture instructions
3. Create your agent with memory enabled
4. Configure additional features like user memory tracking
5. Create the WhatsApp API app instance

The memory system allows you to:
- Store and retrieve user information
- Track conversation context
- Maintain persistent data across sessions
- Customize what information to capture and store

## Features

### Message Handling
- Automatic response generation
- Message history tracking
- Markdown support
- Datetime awareness

### Memory Management
- Persistent storage using SQLite
- User information collection
- Context-aware responses
- Session management

### Tools Integration
- DuckDuckGo search
- YouTube resource recommendations
- Custom tool support

## Security Considerations
- Use HTTPS for all communications
- Secure storage of API tokens
- Regular token rotation
- Webhook verification

## Error Handling
The module includes comprehensive error handling for:
- Webhook verification failures
- Message processing errors
- API communication issues
- Storage system errors

## Best Practices
1. Always use environment variables for sensitive data
2. Implement proper error handling
3. Use memory features for personalized interactions
4. Regular monitoring of API usage
5. Keep dependencies updated

## Troubleshooting
Common issues and solutions:
1. Webhook verification failures
   - Check verify token
   - Verify ngrok connection
   - Confirm webhook URL

2. Message delivery issues
   - Verify API credentials
   - Check phone number ID
   - Confirm webhook subscription

3. Memory/storage problems
   - Check database permissions
   - Verify storage paths
   - Monitor disk space

## Support
For additional support:
1. Check the application logs
2. Review Meta's WhatsApp Business API documentation
3. Verify API credentials and tokens
4. Monitor ngrok connection status
