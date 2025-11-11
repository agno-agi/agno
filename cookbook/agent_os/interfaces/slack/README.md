# Slack API Integration Setup Guide

This guide will help you set up and configure the Slack API integration for your application.

## Prerequisites

- Python 3.7+
- A Slack workspace where you have admin privileges
- ngrok (for local development)

## Setup Steps

### 1. Create a Slack App

1. Go to the Slack App Directory (https://api.slack.com/apps)
2. Click "Create New App"
3. Select "From scratch"
4. Give your app a name and select a workspace
5. Click "Create App"

### 2. Configure OAuth & Permissions

1. Go to "OAuth & Permissions" in your Slack App settings
2. Click "Add Scopes"
3. Add the following scopes:
   - `app_mention`
   - `chat:write`
   - `chat:write.customize`
   - `chat:write.public`
   - `im:history`
   - `im:read`
   - `im:write`

### 3. Install to your workspace

1. Go to "Install App" in your Slack App settings
2. Click "Install to Workspace"
3. Authorize the app

You'll have to repeat this step if you change any scopes/permissions.


### 4. Configure Environment Variables

Save the following credentials as environment variables:

```bash
export SLACK_TOKEN="xoxb-your-bot-user-token"  # Bot User OAuth Token
export SLACK_SIGNING_SECRET="your-signing-secret"  # App Signing Secret
```

You can find these values in your Slack App settings:
- Bot User OAuth Token: Under "OAuth & Permissions"
- Signing Secret: Under "Basic Information" > "App Credentials"

### 5 Run Ngrok
   1. For local testing with Agno's SlackApp and agents, we recommend using ngrok to create a secure tunnel to your local server. It is also easier if you get a static url from ngrok.
   2. Run ngrok:
   ```bash
   ngrok http --url=your-url.ngrok-free.app http://localhost:8000
   ```
   3. Run your app locally with `python <my-app>.py`


### 6. Configure Event Subscriptions

1. Go to "Event Subscriptions" in your Slack App settings
2. Enable events by toggling the switch
3. Add your ngrok URL + "/slack/events" to the Request URL (or with a custom prefix)
   - Example: `https://your-ngrok-url.ngrok.io/slack/events` (or with a custom prefix: `https://your-ngrok-url.ngrok.io/custom-prefix/events`)
4. Make sure your app is running with ngrok, then verify the request URL
5. Subscribe to events based on your use case:
   
   **Option 1: Only respond to mentions (recommended for most bots)**
   - Subscribe to: `app_mention`
   - The bot will only respond when explicitly mentioned with `@YourAppName`
   - This prevents the bot from responding to all messages in channels
   
   **Option 2: Respond to all messages (use with caution)**
   - Subscribe to: `app_mention`, `message.im`, `message.channels`, `message.groups`
   - The bot will respond to all messages in channels where it's a member
   - Note: If you subscribe to `message.channels`, the bot will respond to all channel messages, not just mentions
   
6. Reinstall the app to your workspace to apply the changes

### 7. Enable Direct Messages

To allow users to send messages to the bot:

1. Go to "App Home" in your Slack App settings
2. Scroll down to "Show Tabs"
3. Check "Allow users to send Slash commands and messages from the messages tab"
4. Reinstall the app to apply changes


## Testing the Integration

1. Start your application locally with `python <my-app>.py` (ensure ngrok is running)
2. Invite the bot to a channel using `/invite @YourAppName`
3. Try mentioning the bot in the channel: `@YourAppName hello`
   - If you've subscribed only to `app_mention`, the bot will respond only when mentioned
   - If you've subscribed to `message.channels`, the bot will respond to all messages in the channel
4. Test direct messages by opening a DM with the bot (requires `message.im` subscription)

## Troubleshooting

- If events aren't being received, verify your ngrok URL is correct and the app is properly installed
- Check that all required environment variables are set
- Ensure the bot has been invited to the channels where you're testing
- Verify that the correct events are subscribed in Event Subscriptions
- **Bot not responding to mentions**: Ensure `app_mention` is subscribed in Event Subscriptions
- **Bot responding to all messages**: If you only want mentions, subscribe only to `app_mention` and remove `message.channels`, `message.groups`, and `message.im` subscriptions

## Support

If you encounter any issues, please check the Slack API documentation or open an issue in the repository. 