# Notion Integration Setup Guide

This guide will help you set up the Notion integration for the query classification workflow.

## Prerequisites

1. A Notion account
2. Python 3.9 or higher
3. Agno framework installed

## Step 1: Install Required Dependencies

```bash
pip install notion-client
```

## Step 2: Create a Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click on **"+ New integration"**
3. Fill in the details:
   - **Name**: Give it a name like "Agno Query Classifier"
   - **Associated workspace**: Select your workspace
   - **Type**: Internal integration
4. Click **"Submit"**
5. Copy the **"Internal Integration Token"** (starts with `secret_`)
   - ⚠️ Keep this secret! This is your `NOTION_API_KEY`

## Step 3: Create a Notion Database

1. Open Notion and create a new page
2. Add a **Database** (you can use "/database" command)
3. Set up the database with these properties:
   - **Name** (Title) - Already exists by default
   - **Tag** (Select) - Click "+" to add a new property
     - Property type: **Select**
     - Property name: **Tag**
     - Add these options:
       - travel
       - tech
       - general-blogs
       - fashion
       - documents

## Step 4: Share Database with Your Integration

1. Open your database page in Notion
2. Click the **"..."** (three dots) menu in the top right
3. Scroll down and click **"Add connections"**
4. Search for your integration name (e.g., "Agno Query Classifier")
5. Click on it to grant access

## Step 5: Get Your Database ID

Your database ID is in the URL of your database page:

```
https://www.notion.so/../{database_id}?v={view_id}
```

The `database_id` is the 32-character string (with hyphens) between the workspace name and the `?v=`.

Example:
```
https://www.notion.so/myworkspace/28fee27fd9128039b3f8f47cb7ade7cb?v=...
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                 This is your database_id
```

Copy this database ID.

## Step 6: Set Environment Variables

Create a `.env` file in your project root or export these variables:

```bash
export NOTION_API_KEY="secret_your_integration_token_here"
export NOTION_DATABASE_ID="your_database_id_here"
export OPENAI_API_KEY="your_openai_api_key_here"
```

Or in a `.env` file:
```
NOTION_API_KEY=secret_your_integration_token_here
NOTION_DATABASE_ID=your_database_id_here
OPENAI_API_KEY=your_openai_api_key_here
```

## Step 7: Run the Workflow

```bash
python cookbook/examples/workflows/thoughts_dump_notion/thoughts_dump_notion.py
```

The server will start on `http://localhost:7777` (or another port).

Go to [AgentOS](https://os.agno.com/) and test!

