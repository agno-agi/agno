# SAMPLE_QUERIES.md - Comprehensive Test Cases for Agno Demo

This document contains sample queries organized by agent/team/workflow, with analysis of prompt quality and expected behaviors.

---

## Prompt Quality Analysis Summary

| Component | Quality | Strengths | Improvement Areas |
|-----------|---------|-----------|-------------------|
| PaL Agent | EXCELLENT | State management, planning guidance, personality | More examples of plan vs no-plan decisions |
| Research Agent | EXCELLENT | 5-step methodology, source hierarchy, conflict resolution | When to stop searching |
| Finance Agent | GOOD | Concise, focused, includes disclaimer | More metric definitions |
| Deep Knowledge Agent | VERY GOOD | Iterative search, reasoning documentation | When to stop iterating |
| Web Intelligence Agent | VERY GOOD | Capabilities, output format, comparison format | Handling blocked content |
| Report Writer Agent | EXCELLENT | Report types, structure template, quality checklist | Examples of good vs bad |
| Knowledge Agent | GOOD | Simple, focused, uncertainty handling | Search strategies |
| MCP Agent | GOOD | Simple, focused | Differentiate from Knowledge Agent |
| Devil's Advocate Agent | EXCELLENT | Critical framework, mindset, steel-manning | Examples |
| Investment Team | EXCELLENT | Team roles, workflow, output structure | - |
| Due Diligence Team | EXCELLENT | Debate concept, disagreement visibility | - |
| Deep Research Workflow | VERY GOOD | 4-phase pipeline, clear roles | - |
| Startup Analyst Workflow | VERY GOOD | VC-style pipeline, comprehensive report | - |

---

## PaL Agent (pal_agent.py)

### Test Category: Simple Questions (NO PLAN expected)

```bash
# These should be answered directly WITHOUT creating a plan

# Basic factual
python cookbook/demo/agents/pal_agent.py "What is the capital of France?"
python cookbook/demo/agents/pal_agent.py "What is 2+2?"
python cookbook/demo/agents/pal_agent.py "Define machine learning in one sentence"
python cookbook/demo/agents/pal_agent.py "Who is the CEO of OpenAI?"

# Quick lookups
python cookbook/demo/agents/pal_agent.py "NVDA stock price"
python cookbook/demo/agents/pal_agent.py "What time is it in Tokyo?"
python cookbook/demo/agents/pal_agent.py "Convert 100 USD to EUR"

# Casual conversation
python cookbook/demo/agents/pal_agent.py "Hello, how are you?"
python cookbook/demo/agents/pal_agent.py "Thanks for your help!"
python cookbook/demo/agents/pal_agent.py "Tell me a joke"
```

**Expected Behavior:** Direct answer, session state shows `status: no_plan`

### Test Category: Complex Tasks (PLAN expected)

```bash
# These SHOULD create a structured plan

# Comparison tasks
python cookbook/demo/agents/pal_agent.py "Help me decide between Supabase, Firebase, and PlanetScale for my startup"
python cookbook/demo/agents/pal_agent.py "Compare AWS, GCP, and Azure for a machine learning project"
python cookbook/demo/agents/pal_agent.py "Which framework should I use for a new web app: Next.js, Remix, or SvelteKit?"

# Research tasks
python cookbook/demo/agents/pal_agent.py "Build a complete competitive analysis of the vector database market"
python cookbook/demo/agents/pal_agent.py "Create a market overview of AI agent frameworks"
python cookbook/demo/agents/pal_agent.py "Research the current state of quantum computing and its commercial applications"

# Investment analysis
python cookbook/demo/agents/pal_agent.py "Full investment analysis of NVIDIA"
python cookbook/demo/agents/pal_agent.py "Compare the tech giants as investments: AAPL, MSFT, GOOGL, META, AMZN"
python cookbook/demo/agents/pal_agent.py "Should I invest in AI stocks? Create a thesis with pros and cons"

# Multi-step projects
python cookbook/demo/agents/pal_agent.py "Help me plan a migration from MongoDB to PostgreSQL"
python cookbook/demo/agents/pal_agent.py "Create a launch plan for a new SaaS product"
python cookbook/demo/agents/pal_agent.py "Build a security audit checklist for my startup"
```

**Expected Behavior:** Creates plan with steps, tracks progress, session state shows `status: in_progress`

### Test Category: Edge Cases

```bash
# Ambiguous - could go either way
python cookbook/demo/agents/pal_agent.py "Tell me about Anthropic"
python cookbook/demo/agents/pal_agent.py "What's happening in AI?"
python cookbook/demo/agents/pal_agent.py "Help me understand LLMs"

# Very complex (tests plan limits)
python cookbook/demo/agents/pal_agent.py "Create a complete business plan for an AI startup including market research, competitive analysis, financial projections, and go-to-market strategy"

# Mid-plan requests (requires existing session)
# "Skip step 2 and move to step 3"
# "Add a new step after the current one"
# "Go back to step 1 and redo it"
```

---

## Research Agent (research_agent.py)

### Test Category: Industry Research

```bash
python cookbook/demo/agents/research_agent.py "Research the current state of AI agents in enterprise"
python cookbook/demo/agents/research_agent.py "What are the latest trends in vector databases?"
python cookbook/demo/agents/research_agent.py "Research the future of serverless computing"
python cookbook/demo/agents/research_agent.py "Analyze the LLM landscape: OpenAI vs Anthropic vs Google vs Meta"
python cookbook/demo/agents/research_agent.py "Research the competitive landscape of observability tools"
```

### Test Category: Controversial Topics (tests balanced reporting)

```bash
python cookbook/demo/agents/research_agent.py "Is AI in a bubble? Present both sides objectively"
python cookbook/demo/agents/research_agent.py "Research: Will AGI arrive by 2030? Arguments for and against"
python cookbook/demo/agents/research_agent.py "Is remote work better than in-office? Present evidence from both sides"
python cookbook/demo/agents/research_agent.py "Research: Are coding interviews effective? Present the debate"
```

### Test Category: Current Events

```bash
python cookbook/demo/agents/research_agent.py "What are the latest AI breakthroughs this month?"
python cookbook/demo/agents/research_agent.py "Recent developments in autonomous vehicles"
python cookbook/demo/agents/research_agent.py "Latest news in the semiconductor industry"
python cookbook/demo/agents/research_agent.py "Recent funding rounds in AI startups"
```

### Test Category: Deep Dives

```bash
python cookbook/demo/agents/research_agent.py "Deep research: How do transformer architectures work? Technical explanation"
python cookbook/demo/agents/research_agent.py "Research the history and evolution of RAG systems"
python cookbook/demo/agents/research_agent.py "Comprehensive research on AI safety approaches and frameworks"
```

### Test Category: Quick Questions (tests conciseness)

```bash
python cookbook/demo/agents/research_agent.py "What is quantum computing in 2 sentences?"
python cookbook/demo/agents/research_agent.py "Define RAG briefly"
python cookbook/demo/agents/research_agent.py "Latest AI news in 3 bullet points"
```

---

## Finance Agent (finance_agent.py)

### Test Category: Single Stock Queries

```bash
python cookbook/demo/agents/finance_agent.py "NVDA price"
python cookbook/demo/agents/finance_agent.py "Give me a quick investment brief on NVDA"
python cookbook/demo/agents/finance_agent.py "AAPL key metrics and P/E ratio"
python cookbook/demo/agents/finance_agent.py "TSLA financial overview with 52-week range"
python cookbook/demo/agents/finance_agent.py "Microsoft (MSFT) fundamentals and dividend yield"
```

### Test Category: Stock Comparisons

```bash
python cookbook/demo/agents/finance_agent.py "Compare AAPL, MSFT, and GOOGL - show me a metrics table"
python cookbook/demo/agents/finance_agent.py "NVDA vs AMD - which is better value?"
python cookbook/demo/agents/finance_agent.py "Compare the FAANG stocks by valuation"
python cookbook/demo/agents/finance_agent.py "Compare semiconductor stocks: NVDA, AMD, INTC, TSM"
```

### Test Category: Sector Analysis

```bash
python cookbook/demo/agents/finance_agent.py "Top AI stocks by market cap"
python cookbook/demo/agents/finance_agent.py "Best performing tech stocks this year"
python cookbook/demo/agents/finance_agent.py "EV stocks overview: TSLA, RIVN, LCID"
```

### Test Category: Specific Metrics

```bash
python cookbook/demo/agents/finance_agent.py "NVDA revenue growth YoY"
python cookbook/demo/agents/finance_agent.py "AAPL dividend history"
python cookbook/demo/agents/finance_agent.py "GOOGL EPS trend over last 4 quarters"
python cookbook/demo/agents/finance_agent.py "META market cap vs peers"
```

### Test Category: Edge Cases

```bash
# Unknown ticker
python cookbook/demo/agents/finance_agent.py "XXXYZ price"

# Ambiguous company
python cookbook/demo/agents/finance_agent.py "Apple stock" # Should clarify AAPL

# Non-US stocks
python cookbook/demo/agents/finance_agent.py "Toyota (TM) overview"
python cookbook/demo/agents/finance_agent.py "Samsung stock"

# Private companies (should handle gracefully)
python cookbook/demo/agents/finance_agent.py "Anthropic stock price"
```

---

## Deep Knowledge Agent (deep_knowledge_agent.py)

### Test Category: Documentation Queries

```bash
python cookbook/demo/agents/deep_knowledge_agent.py "What is Agno and what are its main features?"
python cookbook/demo/agents/deep_knowledge_agent.py "How do I create an agent with tools in Agno?"
python cookbook/demo/agents/deep_knowledge_agent.py "Explain the difference between Agent, Team, and Workflow in Agno"
python cookbook/demo/agents/deep_knowledge_agent.py "How do I add memory to an Agno agent?"
```

### Test Category: Code Generation

```bash
python cookbook/demo/agents/deep_knowledge_agent.py "Show me how to create an agent with web search capabilities"
python cookbook/demo/agents/deep_knowledge_agent.py "Write code to create a team of agents that work together"
python cookbook/demo/agents/deep_knowledge_agent.py "How do I implement RAG with Agno? Show me complete code"
python cookbook/demo/agents/deep_knowledge_agent.py "Create an agent that uses YFinance tools"
```

### Test Category: Conceptual Questions

```bash
python cookbook/demo/agents/deep_knowledge_agent.py "What is the best way to structure a multi-agent system?"
python cookbook/demo/agents/deep_knowledge_agent.py "When should I use a Team vs a Workflow?"
python cookbook/demo/agents/deep_knowledge_agent.py "How does Agno handle agent memory and context?"
python cookbook/demo/agents/deep_knowledge_agent.py "What are best practices for prompting agents in Agno?"
```

### Test Category: Iterative Reasoning (tests multiple searches)

```bash
python cookbook/demo/agents/deep_knowledge_agent.py "Comprehensive guide to building production-ready agents with Agno"
python cookbook/demo/agents/deep_knowledge_agent.py "All the ways to persist agent state in Agno - compare approaches"
```

---

## Web Intelligence Agent (web_intelligence_agent.py)

### Test Category: Company Analysis

```bash
python cookbook/demo/agents/web_intelligence_agent.py "Analyze anthropic.com - give me a quick summary of what they do"
python cookbook/demo/agents/web_intelligence_agent.py "Analyze openai.com - products, pricing, and positioning"
python cookbook/demo/agents/web_intelligence_agent.py "What does stripe.com offer? Extract their main products"
python cookbook/demo/agents/web_intelligence_agent.py "Analyze notion.so - target audience and key features"
```

### Test Category: Competitive Analysis

```bash
python cookbook/demo/agents/web_intelligence_agent.py "Compare OpenAI and Anthropic based on their websites"
python cookbook/demo/agents/web_intelligence_agent.py "Compare Stripe vs Square - key differences"
python cookbook/demo/agents/web_intelligence_agent.py "Vercel vs Netlify - compare their offerings"
python cookbook/demo/agents/web_intelligence_agent.py "Compare the top 3 cloud providers' landing pages"
```

### Test Category: Pricing Intelligence

```bash
python cookbook/demo/agents/web_intelligence_agent.py "Extract pricing information from github.com"
python cookbook/demo/agents/web_intelligence_agent.py "What are Slack's pricing tiers?"
python cookbook/demo/agents/web_intelligence_agent.py "Compare pricing: Notion vs Coda vs Airtable"
```

### Test Category: Product Intelligence

```bash
python cookbook/demo/agents/web_intelligence_agent.py "What products does Datadog offer?"
python cookbook/demo/agents/web_intelligence_agent.py "Extract all features listed on linear.app"
python cookbook/demo/agents/web_intelligence_agent.py "What integrations does Zapier support?"
```

---

## Report Writer Agent (report_writer_agent.py)

### Test Category: Executive Summaries

```bash
python cookbook/demo/agents/report_writer_agent.py "Write a brief executive summary on the state of AI agents in 2025"
python cookbook/demo/agents/report_writer_agent.py "Executive summary: Cloud computing market in 5 bullet points"
python cookbook/demo/agents/report_writer_agent.py "Quick executive summary on the rise of AI-native companies"
```

### Test Category: Market Analysis Reports

```bash
python cookbook/demo/agents/report_writer_agent.py "Write a short market analysis report on the cloud computing industry"
python cookbook/demo/agents/report_writer_agent.py "Market analysis: The AI chip industry"
python cookbook/demo/agents/report_writer_agent.py "Report on the state of developer tools market"
```

### Test Category: Technical Reports

```bash
python cookbook/demo/agents/report_writer_agent.py "Write a technical report on RAG architectures"
python cookbook/demo/agents/report_writer_agent.py "Technical analysis: Vector database performance comparison"
python cookbook/demo/agents/report_writer_agent.py "Report on microservices vs monolith architectures"
```

### Test Category: Structured Content

```bash
python cookbook/demo/agents/report_writer_agent.py "Write 3 bullet points about AI safety"
python cookbook/demo/agents/report_writer_agent.py "Create a comparison table: PostgreSQL vs MongoDB vs DynamoDB"
python cookbook/demo/agents/report_writer_agent.py "Write a pros and cons list for adopting Kubernetes"
```

---

## Knowledge Agent (knowledge_agent.py)

### Test Category: General Questions

```bash
python cookbook/demo/agents/knowledge_agent.py "What is Agno and what are its main features?"
python cookbook/demo/agents/knowledge_agent.py "How do agents work in Agno?"
python cookbook/demo/agents/knowledge_agent.py "What databases does Agno support?"
```

### Test Category: Code Examples

```bash
python cookbook/demo/agents/knowledge_agent.py "Show me how to create an agent with web search capabilities"
python cookbook/demo/agents/knowledge_agent.py "How do I create a team of agents?"
python cookbook/demo/agents/knowledge_agent.py "Write code to implement a RAG agent"
```

### Test Category: Advanced Topics

```bash
python cookbook/demo/agents/knowledge_agent.py "How do I implement custom tools in Agno?"
python cookbook/demo/agents/knowledge_agent.py "Explain the memory system in Agno"
python cookbook/demo/agents/knowledge_agent.py "How do workflows differ from teams?"
```

---

## MCP Agent (mcp_agent.py)

### Test Category: General Questions

```bash
python cookbook/demo/agents/mcp_agent.py "What is Agno?"
python cookbook/demo/agents/mcp_agent.py "How do I create a simple agent?"
python cookbook/demo/agents/mcp_agent.py "What is MCP and how does it work?"
```

### Test Category: Search Queries

```bash
python cookbook/demo/agents/mcp_agent.py "Search for information about teams in Agno"
python cookbook/demo/agents/mcp_agent.py "Find documentation about workflows"
python cookbook/demo/agents/mcp_agent.py "Search for examples of RAG agents"
```

### Test Category: Code Requests

```bash
python cookbook/demo/agents/mcp_agent.py "Show me how to create a simple agent"
python cookbook/demo/agents/mcp_agent.py "Code example for using MCP tools"
```

---

## Devil's Advocate Agent (devil_advocate_agent.py)

### Test Category: Investment Thesis Challenges

```bash
python cookbook/demo/agents/devil_advocate_agent.py "Challenge this thesis: NVIDIA will dominate AI infrastructure for the next decade"
python cookbook/demo/agents/devil_advocate_agent.py "Challenge: AI will replace 50% of knowledge work jobs by 2030"
python cookbook/demo/agents/devil_advocate_agent.py "Challenge the thesis that OpenAI will remain the AI market leader"
```

### Test Category: Strategy Reviews

```bash
python cookbook/demo/agents/devil_advocate_agent.py "What could go wrong with betting heavily on AI stocks right now?"
python cookbook/demo/agents/devil_advocate_agent.py "Challenge this strategy: Going all-in on cloud-native architecture"
python cookbook/demo/agents/devil_advocate_agent.py "What are the risks of early AI adoption for enterprises?"
```

### Test Category: Analysis Challenges

```bash
python cookbook/demo/agents/devil_advocate_agent.py "Find the flaws in the bull case for Anthropic"
python cookbook/demo/agents/devil_advocate_agent.py "Challenge the assumption that LLMs will keep improving at current rates"
python cookbook/demo/agents/devil_advocate_agent.py "What's wrong with the 'AI will solve climate change' argument?"
```

### Test Category: Counter-Arguments

```bash
python cookbook/demo/agents/devil_advocate_agent.py "Present the bear case for Tesla"
python cookbook/demo/agents/devil_advocate_agent.py "What would make the AI hype crash?"
python cookbook/demo/agents/devil_advocate_agent.py "Arguments against investing in quantum computing startups"
```

---

## Investment Team (teams/investment_team.py)

### Test Category: Single Stock Analysis

```bash
python cookbook/demo/teams/investment_team.py "Give me a quick investment analysis of NVDA"
python cookbook/demo/teams/investment_team.py "Complete investment analysis of NVIDIA"
python cookbook/demo/teams/investment_team.py "Should I buy AAPL? Give me a recommendation"
python cookbook/demo/teams/investment_team.py "Investment thesis for Tesla"
```

### Test Category: Stock Comparisons

```bash
python cookbook/demo/teams/investment_team.py "Compare AAPL and MSFT as investments - which is better?"
python cookbook/demo/teams/investment_team.py "Should I invest in Microsoft, Google, or Amazon?"
python cookbook/demo/teams/investment_team.py "Compare semiconductor stocks: NVDA, AMD, INTC, TSM"
python cookbook/demo/teams/investment_team.py "Best AI stock to buy: NVDA, GOOGL, or MSFT?"
```

### Test Category: Sector Analysis

```bash
python cookbook/demo/teams/investment_team.py "Investment outlook for the AI sector"
python cookbook/demo/teams/investment_team.py "Should I invest in EV stocks?"
python cookbook/demo/teams/investment_team.py "Tech stocks investment analysis for 2025"
```

### Test Category: Quick Summaries

```bash
python cookbook/demo/teams/investment_team.py "Quick summary of AAPL - 3 bullet points"
python cookbook/demo/teams/investment_team.py "NVDA key metrics only"
```

---

## Due Diligence Team (teams/due_diligence_team.py)

### Test Category: Company Due Diligence

```bash
python cookbook/demo/teams/due_diligence_team.py "Quick due diligence on Anthropic - give me a verdict"
python cookbook/demo/teams/due_diligence_team.py "Due diligence on Anthropic - should we invest?"
python cookbook/demo/teams/due_diligence_team.py "Full due diligence on OpenAI"
python cookbook/demo/teams/due_diligence_team.py "Evaluate Stripe as a potential acquisition target"
```

### Test Category: Partnership Evaluation

```bash
python cookbook/demo/teams/due_diligence_team.py "Evaluate OpenAI as a strategic partner"
python cookbook/demo/teams/due_diligence_team.py "Should we partner with Anthropic? Due diligence"
python cookbook/demo/teams/due_diligence_team.py "Partnership analysis: AWS vs GCP vs Azure"
```

### Test Category: Investment Evaluation (with debate)

```bash
python cookbook/demo/teams/due_diligence_team.py "Evaluate NVIDIA as an investment - is it overvalued?"
python cookbook/demo/teams/due_diligence_team.py "TSLA investment analysis with bull and bear cases"
python cookbook/demo/teams/due_diligence_team.py "Should we invest in AI infrastructure stocks?"
```

### Test Category: Risk-Focused Analysis

```bash
python cookbook/demo/teams/due_diligence_team.py "What are the top 5 risks of investing in Anthropic?"
python cookbook/demo/teams/due_diligence_team.py "Risk analysis: Going all-in on NVIDIA"
python cookbook/demo/teams/due_diligence_team.py "Due diligence on crypto exchange companies - focus on risks"
```

---

## Deep Research Workflow (workflows/deep_research_workflow.py)

### Test Category: Industry Research

```bash
python cookbook/demo/workflows/deep_research_workflow.py "Deep research: What's the future of AI agents in enterprise?"
python cookbook/demo/workflows/deep_research_workflow.py "Research the current state of AI agents in enterprise"
python cookbook/demo/workflows/deep_research_workflow.py "Comprehensive research on climate tech investment opportunities"
python cookbook/demo/workflows/deep_research_workflow.py "In-depth analysis of the LLM landscape in 2025"
```

### Test Category: Technology Research

```bash
python cookbook/demo/workflows/deep_research_workflow.py "Deep research: Vector database technologies and their future"
python cookbook/demo/workflows/deep_research_workflow.py "Comprehensive research on edge computing trends"
python cookbook/demo/workflows/deep_research_workflow.py "Research the evolution of RAG architectures"
```

### Test Category: Market Research

```bash
python cookbook/demo/workflows/deep_research_workflow.py "Deep research: AI infrastructure market opportunity"
python cookbook/demo/workflows/deep_research_workflow.py "Research the future of developer tools"
python cookbook/demo/workflows/deep_research_workflow.py "Comprehensive analysis of the observability market"
```

### Test Category: Quick Summaries (tests conciseness)

```bash
python cookbook/demo/workflows/deep_research_workflow.py "Research the state of AI agents - keep it brief"
```

---

## Startup Analyst Workflow (workflows/startup_analyst_workflow.py)

### Test Category: Startup Analysis

```bash
python cookbook/demo/workflows/startup_analyst_workflow.py "Analyze this startup: Anthropic"
python cookbook/demo/workflows/startup_analyst_workflow.py "Quick due diligence on Anthropic - give me a brief verdict"
python cookbook/demo/workflows/startup_analyst_workflow.py "Due diligence on: OpenAI"
python cookbook/demo/workflows/startup_analyst_workflow.py "Evaluate this company as an acquisition target: Notion"
```

### Test Category: Investment Decisions

```bash
python cookbook/demo/workflows/startup_analyst_workflow.py "Should we invest in or partner with: Stripe?"
python cookbook/demo/workflows/startup_analyst_workflow.py "Investment analysis: Databricks"
python cookbook/demo/workflows/startup_analyst_workflow.py "Should we acquire: Linear?"
```

### Test Category: Competitive Analysis

```bash
python cookbook/demo/workflows/startup_analyst_workflow.py "Analyze Anthropic vs OpenAI - which is the better investment?"
python cookbook/demo/workflows/startup_analyst_workflow.py "Compare Vercel vs Netlify as investment opportunities"
```

### Test Category: Quick Verdicts

```bash
python cookbook/demo/workflows/startup_analyst_workflow.py "Quick verdict on Anthropic - yes or no?"
python cookbook/demo/workflows/startup_analyst_workflow.py "Should we invest in Hugging Face? Brief analysis"
```

---

## Cross-Component Test Scenarios

### Scenario 1: Full Investment Research Pipeline

```bash
# Step 1: Quick financial data
python cookbook/demo/agents/finance_agent.py "NVDA key metrics"

# Step 2: Qualitative research
python cookbook/demo/agents/research_agent.py "Latest news and analyst opinions on NVIDIA"

# Step 3: Challenge the bull case
python cookbook/demo/agents/devil_advocate_agent.py "Challenge the bull case for NVIDIA"

# Step 4: Full team analysis
python cookbook/demo/teams/investment_team.py "Complete investment analysis of NVIDIA"
```

### Scenario 2: Due Diligence Pipeline

```bash
# Step 1: Company profile
python cookbook/demo/agents/web_intelligence_agent.py "Analyze anthropic.com"

# Step 2: Market research
python cookbook/demo/agents/research_agent.py "Research Anthropic's market position and competitors"

# Step 3: Critical review
python cookbook/demo/agents/devil_advocate_agent.py "What could go wrong with investing in Anthropic?"

# Step 4: Full workflow
python cookbook/demo/workflows/startup_analyst_workflow.py "Complete due diligence on Anthropic"
```

### Scenario 3: Research Deep Dive

```bash
# Step 1: Quick overview
python cookbook/demo/agents/research_agent.py "What is the AI agent market?"

# Step 2: Deep knowledge search
python cookbook/demo/agents/deep_knowledge_agent.py "What are the best practices for building AI agents?"

# Step 3: Full workflow
python cookbook/demo/workflows/deep_research_workflow.py "Deep research on the future of AI agents"
```

---

## Edge Cases and Stress Tests

### Ambiguous Queries

```bash
# These should prompt for clarification or make reasonable assumptions
python cookbook/demo/agents/finance_agent.py "Apple"
python cookbook/demo/agents/research_agent.py "AI"
python cookbook/demo/agents/pal_agent.py "Help me"
```

### Very Long Queries

```bash
python cookbook/demo/agents/pal_agent.py "I want to build a comprehensive investment portfolio that includes AI stocks, semiconductor companies, cloud providers, and some defensive positions. I need you to analyze each sector, compare the top 3 companies in each, create a diversification strategy, and then recommend specific allocation percentages with entry points and stop-loss levels."
```

### Non-English Content

```bash
python cookbook/demo/agents/research_agent.py "Recherche sur l'industrie de l'IA en France"
python cookbook/demo/agents/research_agent.py "Research Japanese tech companies"
```

### Rapid-Fire Queries (test memory/context)

```bash
# Run these in sequence in the same session
python cookbook/demo/agents/pal_agent.py "Analyze NVDA"
python cookbook/demo/agents/pal_agent.py "Compare it to AMD"
python cookbook/demo/agents/pal_agent.py "Which is better for long-term?"
python cookbook/demo/agents/pal_agent.py "What about INTC?"
```

### Empty/Minimal Input

```bash
python cookbook/demo/agents/pal_agent.py ""
python cookbook/demo/agents/pal_agent.py "?"
python cookbook/demo/agents/pal_agent.py "yes"
```

---

## Expected Failure Cases

These should fail gracefully with clear error messages:

```bash
# Invalid ticker
python cookbook/demo/agents/finance_agent.py "XYZABC123 stock price"

# Private company financials
python cookbook/demo/agents/finance_agent.py "Anthropic stock price and P/E ratio"

# Impossible requests
python cookbook/demo/agents/research_agent.py "What will happen tomorrow?"
python cookbook/demo/agents/finance_agent.py "Predict NVDA price next week"
```

---

## Running Tests

### Quick Validation (5 minutes)

```bash
cd /Users/ab/code/agno/cookbook/demo

# PaL Agent - simple vs complex
python agents/pal_agent.py "What is 2+2?"
python agents/pal_agent.py "Help me compare Supabase vs Firebase"

# Finance Agent
python agents/finance_agent.py "NVDA price"

# Research Agent
python agents/research_agent.py "Latest AI news in 3 points"

# Investment Team
python teams/investment_team.py "Quick analysis of AAPL"
```

### Full Test Suite (30+ minutes)

Run each section above with at least 2-3 queries per category.

### Stress Test

Run the Deep Research Workflow and Startup Analyst Workflow with full queries (2-5 minutes each).

---

## Notes

- Teams and workflows take longer (30s-2min) due to multi-agent coordination
- Knowledge agents require loading knowledge base first
- MCP agent requires docs.agno.com/mcp server to be available
- All agents require PostgreSQL with pgvector running

**Last Updated:** 2026-01-19
