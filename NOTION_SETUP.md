# Notion Integration Setup Guide

This guide will help you set up the Notion integration for the query classification workflow.

## Prerequisites

1. A Notion account
2. Python 3.7 or higher
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
https://www.notion.so/{workspace_name}/{database_id}?v={view_id}
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
cd /Users/kaustubh/Desktop/Agno/agno/libs/agno/agno
python test.py
```

The server will start on `http://localhost:8000` (or another port).

## Step 8: Test the Workflow

### Option 1: Using the Web UI
1. Open your browser to `http://localhost:8000`
2. Navigate to the workflow interface
3. Send a test query like: "Best places to visit in Tokyo"
4. Check your Notion database - a new page should appear with the "travel" tag!

### Option 2: Using cURL
```bash
curl -X POST http://localhost:8000/v1/workflows/query-to-notion-workflow/run \
  -H "Content-Type: application/json" \
  -d '{
    "input": "How to build a React application",
    "stream": false
  }'
```

### Option 3: Using Python
```python
import httpx

response = httpx.post(
    "http://localhost:8000/v1/workflows/query-to-notion-workflow/run",
    json={
        "input": "Latest fashion trends for 2025",
        "stream": False
    }
)
print(response.json())
```

## How It Works

1. **Step 1 - Classification**: 
   - User sends a query (e.g., "Best beaches in Bali")
   - The `classify_query` function uses GPT-4o-mini to classify it into one of the tags
   - Returns the tag (e.g., "travel")

2. **Step 2 - Notion Management**:
   - The Notion agent receives the query and tag
   - Searches for existing pages with that tag
   - If found: Updates the existing page with new content
   - If not found: Creates a new page with the tag
   - Returns the page URL and status

## Example Queries to Test

- **Travel**: "Best places to visit in Italy"
- **Tech**: "How to build a REST API with FastAPI"
- **Fashion**: "Summer fashion trends 2025"
- **Documents**: "My project documentation and notes"
- **General Blogs**: "Thoughts on productivity and life"

## Troubleshooting

### Error: "object not found"
- Make sure you've shared the database with your integration (Step 4)
- Verify your database ID is correct

### Error: "unauthorized"
- Check that your `NOTION_API_KEY` is correct
- Make sure the integration token hasn't expired

### Error: "validation_error"
- Ensure your database has a "Tag" property of type "Select"
- Verify the tag options match exactly: travel, tech, general-blogs, fashion, documents

### Agent creates new page instead of updating existing one
- The agent will search for pages with the same tag
- If you want to update a specific page, you might need to adjust the search logic
- Currently, it searches by tag and will update the first matching page

## Customization

### Add More Tags
1. Update the `valid_tags` list in `test.py` (line 44)
2. Add the tag options in your Notion database
3. Update the classifier instructions with examples for new tags

### Change Classification Logic
Modify the `classify_query` function in `test.py` to use different classification methods:
- Use structured output with Pydantic
- Use a different model
- Add more sophisticated classification logic

### Enhance Notion Integration
Extend the `NotionTools` class in `libs/agno/agno/tools/notion.py`:
- Add page deletion
- Add block-level operations
- Add image/file uploads
- Add more complex queries

## Next Steps

- Add more sophisticated search logic (search by title + tag)
- Implement page archiving for old content
- Add rich text formatting support
- Integrate with other tools (Slack notifications, email, etc.)
- Add analytics to track which tags are most common

## Resources

- [Notion API Documentation](https://developers.notion.com/)
- [notion-client Python SDK](https://pypi.org/project/notion-client/)
- [Agno Framework Documentation](https://docs.agno.com)

