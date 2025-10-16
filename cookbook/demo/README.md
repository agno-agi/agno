# AgentOS Demo

This cookbook contains comprehensive demonstrations of Agno's capabilities including both basic functionality and enterprise-grade advanced features.

## Demo Files

- **`real_world_showcase.py`** - 3 comprehensive consumer/lifestyle agents (Lifestyle Concierge + Study Buddy + Creative Studio)
- **`run.py`** - AgentOS production setup with agents, teams, and workflows
- **`teams/oss_maintainer_team.py`** - Enterprise OSS project management team with GitHub integration

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
uv venv .demoenv --python 3.12
source .demoenv/bin/activate
```

### 2. Install libraries

```shell
uv pip install -r cookbook/demo/requirements.txt
```

### 3. Run PgVector

Let's use Postgres for storing data and `PgVector` for vector search.

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/scripts/run_pgvector.sh
```

- OR run using the docker run command

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

### 4. Load data

Load F1 data into the database.

```shell
python cookbook/demo/sql/load_f1_data.py
```

Load F1 knowledge base

```shell
python cookbook/demo/sql/load_knowledge.py
```

### 5. Export API Keys

We recommend using claude-3-7-sonnet for this task, but you can use any Model you like.

```shell
export ANTHROPIC_API_KEY=***
```

Other API keys are optional, but if you'd like to test:

```shell
export OPENAI_API_KEY=***
export GOOGLE_API_KEY=***
export GROQ_API_KEY=***
```

### 6. Run demos

**Option A: Real-World Showcase Demo**

```shell
# Activate your virtual environment
source venv/bin/activate

# Export API keys
export OPENAI_API_KEY='your-openai-key'
export ANTHROPIC_API_KEY='your-anthropic-key'

# Run real-world showcase (3 comprehensive agents: Lifestyle Concierge + Study Buddy + Creative Studio)
python cookbook/demo/real_world_showcase.py
```

Then open [os.agno.com](https://os.agno.com/) and connect to http://localhost:7780 to interact with real-world use cases.

**Option B: Full AgentOS with Teams**

```shell
# Export GitHub token for OSS Maintainer team (optional)
export GITHUB_ACCESS_TOKEN='your-github-token'

# Run full AgentOS with agents, teams (including OSS Maintainer), and workflows
python cookbook/demo/run.py
```

Then open [os.agno.com](https://os.agno.com/) and connect to http://localhost:7777 to interact with all agents and teams.

---

## Demo Files Overview

### `real_world_showcase.py` - Production-Ready Use Cases

**3 Comprehensive Consumer/Lifestyle Agents:**

#### 1. Lifestyle Concierge
Multi-domain personal assistant for finance, shopping, and travel planning.

**Features Demonstrated:**
- Tools (YFinanceTools, DuckDuckGoTools)
- Structured Outputs (Pydantic schemas for finance/shopping/travel)
- Guardrails (PII detection, prompt injection protection)
- Memory (user preferences, conversation history)
- Storage (persistent SQLite database)
- Agent State (shopping cart, travel preferences)

**Sample Prompts:**
```
# Test Tools + Structured Outputs
"Analyze AAPL stock and give me investment recommendations with key metrics"

# Test Tools + Agent State (Shopping Cart)
"Help me find the best noise-cancelling headphones under $300"
"Add the Sony WH-1000XM5 to my cart at $299"
"Show me my shopping cart"

# Test Tools + Agent State (Travel Preferences)
"Plan a 5-day trip to Tokyo with daily activities and budget breakdown"
"Save my travel preferences: destination Tokyo, budget $3000, interests food and technology"
"What are my saved travel preferences?"

# Test Guardrails (should be blocked)
"My email is john@example.com and SSN is 123-45-6789. Help me invest."
```

#### 2. Study Buddy
Educational AI with RAG capabilities and knowledge base search.

**Features Demonstrated:**
- Knowledge/RAG (LanceDB vector database with hybrid search)
- Pre-Hooks (input validation, crisis detection, academic integrity)
- Tool Hooks (monitoring and logging with pre/post hooks)
- Memory (learning progress tracking)
- Storage (persistent conversation history)

**Sample Prompts:**
```
# Test Knowledge Base (RAG)
"Explain Python functions and data structures with examples and best practices"

# Test Tool Hooks (monitoring visible in logs)
"Search for educational resources about machine learning and assess my understanding"

# Test Web Search Tool
"What are the latest trends in artificial intelligence?"
```

#### 3. Creative Studio
Multimodal AI assistant with image generation and analysis capabilities.

**Features Demonstrated:**
- Multimodal (DALL-E image generation, GPT-4o vision)
- Tool Hooks (pre/post hooks for monitoring)
- Guardrails (PII detection, prompt injection protection)
- Storage (persistent conversation history)

**Sample Prompts:**
```
# Test Multimodal (Image Generation)
"Create a futuristic cityscape with flying cars at sunset in cyberpunk style"
"Generate an image of a minimalist logo for a tech startup"

# Test Tool Hooks (monitoring visible in logs)
"Find creative inspiration for a minimalist website design with modern color palettes"

# Test Guardrails (should be blocked)
"Create an image with my SSN 123-45-6789 displayed prominently"
"Generate an image for John Smith, email john.smith@example.com"
```

#### 4. OSS Maintainer Intelligence Team
Enterprise-grade team for managing open source projects with GitHub integration.

**Features Demonstrated:**
- Teams (5 specialized agents with intelligent delegation)
- Sessions (multi-turn PR reviews and issue management)
- Memory (contributor history, project patterns, past decisions)
- Knowledge Base (project documentation and coding standards with LanceDB)
- State Management (project metrics, priority queues, release schedules)
- GitHub Integration (real-time data fetching with GithubTools)
- Database (PostgreSQL for persistent sessions and memory)
- Team Coordination (intelligent routing based on task type)

**Team Composition:**
- **PR Review Council** - Comprehensive code review expert using Claude
- **Issue Triage Specialist** - Intelligent categorization and prioritization
- **Security Guardian** - Vulnerability detection and security analysis
- **Community Relations Manager** - Contributor engagement and communication
- **Release Coordinator** - Changelog generation and release planning

**GitHub Integration Setup:**
```bash
# Enable real GitHub data fetching (optional)
export GITHUB_ACCESS_TOKEN="your_github_token"

# Without token: team analyzes based on text descriptions
# With token: team fetches real PR/issue data from repositories
```

**Sample Prompts:**
```
# Test PR Review with GitHub Integration
"Review PR #4983 from agno-agi/agno repository"
"Can you review this PR: https://github.com/agno-agi/agno/pull/4983"

# Test Issue Triage
"Triage issue #156: Memory leak occurring after 24 hours of continuous operation"
"Categorize and prioritize this bug: Users report gradual slowdown and crashes"

# Test Security Analysis
"Perform security audit on PR #342: OAuth2 authentication with JWT tokens"
"Check for vulnerabilities in this code change: [paste code]"

# Test Community Management
"Help me respond to a first-time contributor who submitted code with style issues"
"Draft a welcoming comment for contributor @username on their first PR"

# Test Release Planning
"Plan release v2.2.0 with 15 merged PRs, 2 breaking changes, and 1 security fix"
"Generate changelog for version 2.2.0 including all recent commits"
```

---

## Running the Demo

```bash
# Enable GitHub integration
export GITHUB_ACCESS_TOKEN='your-github-token'
python cookbook/demo/real_world_showcase.py

# Then connect to https://os.agno.com to interact with all agents
# API available at http://localhost:7780
```

---

## Additional Resources

For questions or support, message us on [Discord](https://agno.link/discord)
