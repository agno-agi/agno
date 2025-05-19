# Content Creator Agent Workflow

Content Creator Workflow is an AI-powered content generation and scheduling tool that converts blog posts into optimized social media content for Twitter and LinkedIn using AI agents.
The system automatically analyzes blog posts and generates platform-specific content that can be edited and scheduled.

---

## 🚀 **Setup Instructions**

> Note: Fork and clone the repository if needed
### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install libraries

```shell
pip install -r cookbook/examples/apps/content_creator/requirements.txt
```

### 3. Typefully API Setup

To enable content scheduling and posting:

- **Create a Typefully Account**: Sign up at typefully.com
- **Get API Key**: Navigate to Typefully settings → Developer → Generate API Key
- **Connect Social Accounts**: In your Typefully dashboard, connect your Twitter and LinkedIn accounts
- **Verify Permissions**: Ensure your Typefully account has permission to post to your connected social accounts

The application uses Typefully's API to schedule and publish your content automatically.
Without a valid Typefully API key and properly connected accounts, the scheduling functionality will not work.

### 4. Export API Keys

```shell
export FIRECRAWL_API_KEY=***
export TYPEFULLY_API_KEY=***
```

We recommend using 'gpt-4o' for this task, but you can also use Mistral 'mistral-large-latest'.

```shell
export OPENAI_API_KEY=***
```

Mistral API key is optional, but if you'd like to test:

```shell
export MISTRAL_API_KEY=***
```

### 5. Run Content Creator Workflow

```shell
streamlit run cookbook/examples/apps/content_creator/app.py
```

- Open [localhost:8501](http://localhost:8501) to view the Content Creator Workflow.

### 6. Features

- **Blog Analysis**: Automatically scrape and analyze blog posts to identify key points and themes
- **Platform-Optimized Content**: Generate tailored content for Twitter threads and LinkedIn posts
- **AI-Powered Generation**: Choose from different AI model providers (OpenAI, Mistral)
- **Content Editing**: Preview and edit generated content before scheduling
- **Automated Scheduling**: Schedule posts for publication at optimal times
- **Typefully Integration**: Publish directly to Twitter and LinkedIn through Typefully

---

### 7. How to Use 🛠

- **Select AI Model**: Choose from OpenAI, Anthropic, Mistral, Gemini, or Groq
- **Choose Platform**: Select Twitter or LinkedIn as your target platform
- **Enter Blog URL**: Paste the URL of the blog post you want to convert
- **Set Schedule**: Choose when you want your content to be published
- **Generate Content**: Click "Analyze Blog & Generate Content" to create your posts
- **Edit Content**: Review and edit the generated content as needed
- **Schedule & Publish**: Send your content to Typefully for scheduling

### 8. Message us on [discord](https://agno.link/discord) if you have any questions
