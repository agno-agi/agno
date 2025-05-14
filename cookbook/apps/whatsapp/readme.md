
[comment]:AI Generated readme

# WhatsApp API Module Documentation

## Overview
The WhatsApp API module provides integration between WhatsApp Business API and AI agents, allowing for automated message handling and responses through WhatsApp. The module is built on FastAPI and supports various agent configurations.

## Module Structure

### Core Components
- `WhatsappAPI`: Main class for creating WhatsApp API endpoints
- `serve_whatsapp_app`: Function to serve the WhatsApp application

### Example Implementations
1. **Basic WhatsApp Agent** (`basicwhatsapp.py`)
   - Simple implementation with basic agent configuration
   - Uses GPT-4 model
   - Includes message history and datetime features

2. **User Memory Agent** (`usermemoryagent.py`)
   - Enhanced implementation with persistent memory
   - Uses SQLite for storage
   - Captures and utilizes user information
   - Features:
     - User name collection
     - Hobbies and interests tracking
     - Personalized responses

3. **Study Buddy Agent** (`whatsappstudyfriend.py`)
   - Specialized educational assistant
   - Features:
     - Memory-based learning
     - DuckDuckGo search integration
     - YouTube resource recommendations
     - Personalized study plans
     - Emotional support capabilities

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
	3. Go to your App page, go to "App settings / Basic" and click "Start Verification" undate "Business Verification".
   1. Associate the app with your business account and click Create App.


1. **Create Meta Developer Account**:
   - Go to [Meta Developer Portal](https://developers.facebook.com/) and create an account
   - 
   - Create a new app at [Meta Apps Dashboard](https://developers.facebook.com/apps/)
     - Go to "App Settings / Advanced" and toggle "Desktop App". 
   - Enable WhatsApp integration for your app

2. **Set Up WhatsApp Business API**:
   - Go to your app's WhatsApp Setup page
   - Find your WhatsApp Business Account ID in Business Settings
   - Get your Phone Number ID from the WhatsApp > Getting Started page
   - Generate a permanent access token in App Dashboard > WhatsApp > API Setup

3. **Test Environment Setup**:
   - Note: Initially, you can only send messages to numbers registered in your test environment
   - For production, you'll need to submit your app for review

### Environment Variables
Create a `.envrc` file with:
```bash
export WHATSAPP_ACCESS_TOKEN=your_whatsapp_access_token
export WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
export WHATSAPP_WEBHOOK_URL=your_webhook_url
export WHATSAPP_VERIFY_TOKEN=your_verify_token
```

### Running the Application
1. Start ngrok:
```bash
ngrok http --domain=your-domain.ngrok-free.app 8000
```

2. Start the WhatsApp API endpoints:
```bash
python <agent_file>.py
```

### WhatsApp Business Setup
1. Go to Meta Developer Portal
2. Set up your WhatsApp Business account
3. Configure the webhook:
   - URL: Your ngrok URL + "/webhook" (e.g., https://your-domain.ngrok-free.app/webhook)
   - Verify Token: Same as WHATSAPP_VERIFY_TOKEN in your .envrc
   - Subscribe to the 'messages' webhook field

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
