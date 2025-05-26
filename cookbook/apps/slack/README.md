# Slack API Integration Setup Guide

This guide will help you set up and configure the Slack API integration for your application.

## Prerequisites

- Python 3.7+
- A Slack workspace where you have admin privileges
- ngrok (for local development)

## Setup Steps

### 1. Install the App to Your Workspace

1. Go to your Slack App settings (api.slack.com/apps)
2. Click "Install to Workspace"
3. Authorize the app

### 2. Configure Environment Variables

Save the following credentials as environment variables:

```bash
export SLACK_TOKEN="xoxb-your-bot-user-token"  # Bot User OAuth Token
export SLACK_SIGNING_SECRET="your-signing-secret"  # App Signing Secret
```

You can find these values in your Slack App settings:
- Bot User OAuth Token: Under "OAuth & Permissions"
- Signing Secret: Under "Basic Information" > "App Credentials"

### 3. Configure Event Subscriptions

1. Go to "Event Subscriptions" in your Slack App settings
2. Enable events by toggling the switch
3. Add your ngrok URL + "/slack/events" to the Request URL
   - Example: `https://your-ngrok-url.ngrok.io/slack/events`
4. Subscribe to the following bot events:
   - `app_mention`
   - `message.channels`
   - `message.im`

### 4. Verify and Save Changes

1. Run your application to verify the URL is working
2. Save all changes in the Slack App settings
3. Reinstall the app to your workspace to apply the changes

### 5. Invite the Bot to Channels

Use the following command in any Slack channel to invite the bot:
```
/invite @YourAppName
```

### 6. Enable Direct Messages

To allow users to send messages to the bot:

1. Go to "App Home" in your Slack App settings
2. Scroll down to "Show Tabs"
3. Check "Allow users to send Slash commands and messages from the messages tab"
4. Reinstall the app to apply changes

## Testing the Integration

1. Start your application
2. Invite the bot to a channel using `/invite @YourAppName`
3. Try mentioning the bot in the channel: `@YourAppName hello`
4. Test direct messages by opening a DM with the bot

## Troubleshooting

- If events aren't being received, verify your ngrok URL is correct and the app is properly installed
- Check that all required environment variables are set
- Ensure the bot has been invited to the channels where you're testing
- Verify that the correct events are subscribed in Event Subscriptions

## Support

If you encounter any issues, please check the Slack API documentation or open an issue in the repository. 