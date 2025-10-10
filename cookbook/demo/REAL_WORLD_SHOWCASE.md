# Real-World Use Cases Showcase

This document provides comprehensive documentation for the **Real-World Use Cases Showcase** - a demonstration of 10 innovative AI applications built with the Agno framework.

## Overview

The Real-World Showcase demonstrates the full capabilities of Agno through practical, production-ready use cases spanning:
- **Customer Support** - Intelligent ticket handling
- **Content Creation** - Automated research, writing & editing
- **Finance** - Investment analysis & advice
- **Legal** - Document analysis & contract review
- **HR** - Recruitment & candidate evaluation
- **E-commerce** - Personalized product recommendations
- **Healthcare** - Symptom checking & health information
- **Business Intelligence** - Data analysis & strategic insights
- **Education** - Adaptive personalized learning
- **Travel** - Comprehensive trip planning

## Quick Start

### Prerequisites

```bash
# Python 3.10+
python --version

# Install dependencies
pip install agno yfinance duckduckgo-search newspaper4k lancedb openai anthropic
```

### Environment Setup

```bash
# Set API keys (optional for demo, required for full functionality)
export OPENAI_API_KEY="your-openai-key"
export ANTHROPIC_API_KEY="your-anthropic-key"
```

### Running the Showcase

```bash
# Start AgentOS
python cookbook/demo/real_world_showcase.py

# Access the application
# API: http://localhost:7780
# UI: https://os.agno.com (connect to localhost:7780)
# Docs: http://localhost:7780/docs
```

## Architecture

### Components

The showcase includes:
- **5 Single Agents** - Specialized individual agents
- **4 Teams** - Multi-agent collaborative systems
- **1 Workflow** - Sequential multi-step process

### Technology Stack

- **Models**: OpenAI (GPT-4o, GPT-4o-mini), Claude (Sonnet 4)
- **Vector DB**: LanceDB with OpenAI embeddings
- **Tools**: YFinance, DuckDuckGo, Newspaper4k
- **Storage**: SQLite for sessions and memories
- **API**: FastAPI (via AgentOS)

## Use Cases Detail

### 1. Customer Support AI Team 🎧

**Type**: Multi-Agent Team
**Members**: Ticket Classifier, Support Resolver, Escalation Manager

**Features**:
- Automated ticket classification (category, priority, sentiment)
- Intelligent issue resolution with empathy
- Escalation detection and management
- User memory for personalized support
- Input validation hooks

**Use Cases**:
- Technical support automation
- Billing inquiries
- Product questions
- Account management

**Example**:
```python
# Via AgentOS API
POST /teams/customer-support-team/run
{
    "input": "I can't access my account and need help resetting my password urgently"
}
```

**Output Structure**:
```python
class SupportTicket:
    category: str  # technical, billing, product, account
    priority: str  # low, medium, high, critical
    sentiment: str  # positive, neutral, negative, angry
    requires_escalation: bool
    estimated_resolution_time: str
    suggested_actions: list[str]
```

---

### 2. Content Creation Pipeline ✍️

**Type**: Workflow
**Stages**: Research → Writing → Editing

**Features**:
- Automated topic research with multiple sources
- AI-powered writing with Claude Sonnet 4
- Professional editing and refinement
- SEO optimization
- Fact-checking across sources

**Use Cases**:
- Blog post generation
- Marketing content creation
- Technical documentation
- Social media content
- Newsletter writing

**Example**:
```python
POST /workflows/content-creation-pipeline/run
{
    "input": "The future of AI in healthcare"
}
```

**Pipeline Flow**:
1. **Researcher**: Searches web, finds sources, compiles research
2. **Writer**: Creates engaging article with structure and examples
3. **Editor**: Refines grammar, clarity, flow, and factual accuracy

---

### 3. Personal Finance Manager 💰

**Type**: Single Agent
**Model**: GPT-4o

**Features**:
- Real-time stock data analysis (YFinance)
- Personalized investment recommendations
- Portfolio tracking and advice
- User memory for financial goals
- Risk assessment and allocation

**Use Cases**:
- Investment portfolio analysis
- Stock recommendations
- Budget planning
- Financial goal tracking
- Market insights

**Example**:
```python
POST /agents/personal-finance-manager/run
{
    "input": "Should I invest in tech stocks? I'm a moderate risk investor with $10K to invest."
}
```

**Output Structure**:
```python
class FinancialAdvice:
    summary: str
    recommendations: list[str]
    risk_level: str
    investment_allocation: dict[str, float]
    next_steps: list[str]
```

---

### 4. Legal Document Analyzer ⚖️

**Type**: Single Agent with RAG
**Model**: Claude Sonnet 4

**Features**:
- Knowledge base of legal documents
- Contract clause analysis
- Risk scoring (0-10 scale)
- Plain-language explanations
- Red flag identification

**Use Cases**:
- Contract review
- Legal document summarization
- Clause interpretation
- Risk assessment
- Compliance checking

**Example**:
```python
POST /agents/legal-document-analyzer/run
{
    "input": "Review this employment contract: [contract text]"
}
```

**Output Structure**:
```python
class LegalAnalysis:
    document_type: str
    key_clauses: list[str]
    potential_issues: list[str]
    recommendations: list[str]
    risk_score: float  # 0.0-10.0
    summary: str
```

**⚠️ Disclaimer**: Educational purposes only. Not a substitute for professional legal advice.

---

### 5. HR Recruitment Assistant Team 👥

**Type**: Multi-Agent Team
**Members**: Resume Screener, Skills Evaluator, Culture Fit Assessor

**Features**:
- Automated resume screening
- Technical skills assessment
- Cultural fit evaluation
- Bias-free scoring
- Interview question generation

**Use Cases**:
- Resume screening automation
- Candidate evaluation
- Interview preparation
- Skills gap analysis
- Hiring recommendations

**Example**:
```python
POST /teams/hr-recruitment-team/run
{
    "input": "Evaluate this candidate for Senior Software Engineer role: [resume text]"
}
```

**Output Structure**:
```python
class CandidateEvaluation:
    candidate_name: str
    overall_score: float  # 0.0-10.0
    strengths: list[str]
    weaknesses: list[str]
    technical_skills_score: float
    experience_score: float
    culture_fit_score: float
    recommendation: str  # strong_hire, hire, maybe, no_hire
    interview_questions: list[str]
    next_steps: str
```

---

### 6. E-commerce Product Recommender 🛍️

**Type**: Single Agent
**Model**: GPT-4o

**Features**:
- Personalized recommendations
- User preference learning
- Shopping history tracking
- Budget-aware suggestions
- Trend identification

**Use Cases**:
- Product recommendations
- Shopping assistance
- Deal finding
- Comparison shopping
- Gift suggestions

**Example**:
```python
POST /agents/ecommerce-product-recommender/run
{
    "input": "I need a laptop for programming, budget $1500, prefer portability"
}
```

**Output Structure**:
```python
class ProductRecommendation:
    products: list[dict]  # name, description, reasoning
    personalization_notes: str
    alternative_categories: list[str]
    trending_items: list[str]
```

---

### 7. Healthcare Symptom Checker Team 🏥

**Type**: Multi-Agent Team with RAG
**Members**: Triage Nurse, Health Specialist

**Features**:
- Symptom urgency assessment
- Knowledge base of medical information
- Educational health recommendations
- Emergency detection
- Self-care guidance

**Use Cases**:
- Symptom checking
- Health information lookup
- Urgency assessment
- Self-care recommendations
- When to see a doctor

**Example**:
```python
POST /teams/healthcare-symptom-checker-team/run
{
    "input": "I have a persistent cough for 3 days with mild fever"
}
```

**Output Structure**:
```python
class HealthAssessment:
    urgency_level: str  # emergency, urgent, moderate, low
    possible_conditions: list[str]
    recommendations: list[str]
    red_flags: list[str]
    self_care_tips: list[str]
    when_to_see_doctor: str
    disclaimer: str
```

**⚠️ Safety Feature**: Emergency keyword detection auto-directs to call 911

**⚠️ Disclaimer**: Educational information only. Always consult healthcare professionals.

---

### 8. Business Intelligence Analyst Team 📊

**Type**: Multi-Agent Team
**Members**: Data Analyst, Insights Generator, Report Writer

**Features**:
- Data pattern analysis
- KPI calculation
- Trend identification
- Strategic recommendations
- Executive-level reporting

**Use Cases**:
- Business performance analysis
- Market trend identification
- Competitive analysis
- Strategic planning
- Executive reporting

**Example**:
```python
POST /teams/bi-analyst-team/run
{
    "input": "Analyze Q4 performance: Revenue $2M (up 15%), Customer churn 8% (up 2%)"
}
```

**Output Structure**:
```python
class BusinessInsights:
    executive_summary: str
    key_metrics: dict[str, float]
    trends: list[str]
    opportunities: list[str]
    risks: list[str]
    recommendations: list[str]
    next_steps: list[str]
```

---

### 9. Education Tutor with Adaptive Learning 📚

**Type**: Single Agent with RAG
**Model**: Claude Sonnet 4

**Features**:
- Personalized learning paths
- Progress tracking across sessions
- Learning style adaptation
- Knowledge base integration
- Practice exercise generation

**Use Cases**:
- Personalized tutoring
- Homework help
- Concept explanation
- Practice generation
- Progress tracking

**Example**:
```python
POST /agents/education-tutor/run
{
    "input": "I'm struggling to understand Python decorators. Can you help?"
}
```

**Output Structure**:
```python
class LearningAssessment:
    student_level: str  # beginner, intermediate, advanced
    strengths: list[str]
    areas_for_improvement: list[str]
    learning_style: str  # visual, auditory, kinesthetic, reading
    recommended_pace: str  # slow, moderate, fast
    next_topics: list[str]
    practice_exercises: list[str]
```

---

### 10. Travel Planning Assistant ✈️

**Type**: Single Agent
**Model**: GPT-4o

**Features**:
- Comprehensive itinerary creation
- Flight and hotel research
- Activity recommendations
- Budget estimation
- Local tips and cultural notes

**Use Cases**:
- Trip planning
- Itinerary creation
- Budget estimation
- Activity recommendations
- Travel logistics

**Example**:
```python
POST /agents/travel-planning-assistant/run
{
    "input": "Plan a 5-day trip to Tokyo, budget $3000, interested in tech and food"
}
```

**Output Structure**:
```python
class TravelItinerary:
    destination: str
    duration: str
    budget_estimate: str
    best_time_to_visit: str
    flight_options: list[str]
    accommodation_options: list[str]
    activities: list[dict]  # by day
    restaurants: list[str]
    local_tips: list[str]
    packing_list: list[str]
    estimated_costs: dict[str, str]
```

---

## Key Features Demonstrated

### 1. Memory & Knowledge

**User Memories**:
- Personal Finance Manager remembers investment preferences
- E-commerce Recommender tracks shopping history
- Education Tutor remembers learning progress

**Knowledge Bases (RAG)**:
- Legal Analyzer: Legal documents and precedents
- Healthcare Team: Medical information database
- Education Tutor: Educational content library

### 2. Team Coordination

**Multi-Agent Collaboration**:
- Customer Support: Classifier → Resolver → Escalation Manager
- HR Recruitment: Screener → Skills Evaluator → Culture Assessor
- Healthcare: Triage Nurse → Health Specialist
- Business Intelligence: Data Analyst → Insights Generator → Report Writer

### 3. Structured Outputs

All agents provide Pydantic-validated outputs:
- Type safety and validation
- Consistent response format
- Easy integration with other systems

### 4. Hooks & Validation

**Pre-Hooks**:
- Customer Support: Input validation
- Healthcare: Emergency detection

**Post-Hooks**:
- Output validation and sanitization

### 5. Async Operations

- Workflow executor runs agents asynchronously
- Knowledge base loading runs in parallel
- Efficient resource utilization

## API Usage

### Basic Agent Call

```bash
curl -X POST "http://localhost:7780/agents/personal-finance-manager/run" \
  -H "Content-Type: application/json" \
  -d '{"input": "What is the current price of AAPL?"}'
```

### Team Call

```bash
curl -X POST "http://localhost:7780/teams/customer-support-team/run" \
  -H "Content-Type: application/json" \
  -d '{"input": "I need help with my account"}'
```

### Workflow Call

```bash
curl -X POST "http://localhost:7780/workflows/content-creation-pipeline/run" \
  -H "Content-Type: application/json" \
  -d '{"input": "AI in education"}'
```

### Streaming Response

```bash
curl -X POST "http://localhost:7780/agents/education-tutor/run" \
  -H "Content-Type: application/json" \
  -d '{"input": "Explain machine learning", "stream": true}'
```

## Configuration

### Environment Variables

```bash
# API Keys (optional for demo)
OPENAI_API_KEY=your-key
ANTHROPIC_API_KEY=your-key

# Database (auto-created)
AGNO_DB_PATH=tmp/real_world.db

# LanceDB (auto-created)
LANCEDB_PATH=tmp/lancedb
```

### Custom Configuration

Edit `workspace/config/config.yaml` to customize:
- Model parameters
- Tool configurations
- Memory settings
- Hook behaviors

## Performance Considerations

### Resource Usage

- **Memory**: ~500MB-1GB depending on knowledge bases
- **Startup Time**: ~10-15 seconds for knowledge base loading
- **Response Time**:
  - Simple agents: 2-5 seconds
  - Teams: 10-20 seconds
  - Workflows: 20-40 seconds

### Optimization Tips

1. **Pre-load knowledge bases** for faster first response
2. **Use streaming** for long-running operations
3. **Implement caching** for repeated queries
4. **Monitor token usage** to control costs

## Production Deployment

### Scaling Recommendations

```yaml
agents:
  - Horizontal scaling with load balancer
  - Separate instances for different use cases
  - Cache frequently accessed knowledge

databases:
  - Move from SQLite to PostgreSQL
  - Implement connection pooling
  - Add read replicas for scalability

monitoring:
  - Add Prometheus metrics
  - Implement distributed tracing
  - Set up error alerting
```

### Security Considerations

- **API Keys**: Use secrets management (AWS Secrets Manager, HashiCorp Vault)
- **Rate Limiting**: Implement per-user rate limits
- **Input Validation**: All inputs are validated via pre-hooks
- **Output Sanitization**: Sensitive data is filtered in post-hooks
- **Authentication**: Add OAuth2/JWT for production

## Troubleshooting

### Common Issues

#### Issue: Knowledge base loading fails

```bash
# Check for OpenAI API key
echo $OPENAI_API_KEY

# Verify URL accessibility
curl -I https://docs.python.org/3/tutorial/index.html
```

#### Issue: Port already in use

```bash
# Find process using port 7780
lsof -i :7780

# Kill the process
kill -9 <PID>
```

#### Issue: Out of memory

```bash
# Reduce knowledge base size
# Or increase system memory
# Or disable unused agents
```

## Development

### Adding a New Use Case

1. **Define the agent/team**:
```python
my_agent = Agent(
    name="My Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[...],
    instructions=[...],
)
```

2. **Add to AgentOS**:
```python
agent_os = AgentOS(
    agents=[..., my_agent],
)
```

3. **Test**:
```bash
python cookbook/demo/real_world_showcase.py
```

### Running Tests

```bash
# Unit tests (if available)
pytest tests/

# Integration tests
python -m cookbook.demo.real_world_showcase
```

## Learn More

- **Agno Documentation**: https://docs.agno.com
- **AgentOS Guide**: https://docs.agno.com/concepts/os/introduction
- **Examples**: https://github.com/agno-ai/agno/tree/main/cookbook
- **Community**: https://discord.gg/agno

## License

This showcase is part of the Agno framework and follows the same license.

## Support

For issues, questions, or contributions:
- GitHub Issues: https://github.com/agno-ai/agno/issues
- Discord: https://discord.gg/agno
- Email: support@agno.com

---

**Built with ❤️ by the Agno Team**
