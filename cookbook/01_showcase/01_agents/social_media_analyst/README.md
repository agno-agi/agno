# Social Media Analyst

A brand intelligence agent that analyzes social media sentiment on X (Twitter), extracting engagement metrics, sentiment trends, and actionable recommendations.

## Quick Start

### 1. Prerequisites

```bash
# Set X API credentials
export X_BEARER_TOKEN=your-bearer-token

# Or use full OAuth credentials
export X_API_KEY=your-api-key
export X_API_SECRET=your-api-secret
export X_ACCESS_TOKEN=your-access-token
export X_ACCESS_SECRET=your-access-secret
```

### 2. Run Examples

```bash
# Brand sentiment analysis
.venvs/demo/bin/python cookbook/01_showcase/01_agents/social_media_analyst/examples/01_brand_analysis.py

# Competitor comparison
.venvs/demo/bin/python cookbook/01_showcase/01_agents/social_media_analyst/examples/02_competitor_compare.py

# Trending topic analysis
.venvs/demo/bin/python cookbook/01_showcase/01_agents/social_media_analyst/examples/03_trending_topic.py
```

## Key Concepts

### Sentiment Classification

The agent classifies tweets into four categories:
- **Positive**: Praise, recommendations, satisfaction
- **Negative**: Complaints, frustration, criticism
- **Neutral**: Information sharing, questions, news
- **Mixed**: Contains both positive and negative elements

### Engagement Pattern Detection

- **Viral Advocacy**: High likes & retweets, low replies
- **Controversy**: Low likes, high replies (ratio > 0.5)
- **Influence**: Verified accounts weighted 1.5x

### Brand Health Score

| Score | Interpretation |
|-------|----------------|
| 9-10 | Overwhelmingly positive, strong advocacy |
| 7-8 | Mostly positive, minor issues |
| 5-6 | Mixed sentiment, notable concerns |
| 3-4 | Predominantly negative, significant issues |
| 1-2 | Crisis level negativity |

## Output Structure

```python
from schemas import SocialMediaReport

report = SocialMediaReport(
    brand_health_score=7.5,
    sentiment=SentimentBreakdown(...),
    top_positive_drivers=["Feature X loved", "Great support"],
    top_negative_drivers=["Pricing concerns", "Bug reports"],
    themes=[ThemeAnalysis(...)],
    risks=[RiskItem(...)],
    recommendations=[Recommendation(...)],
    executive_summary="..."
)
```

## Architecture

```
User Query (Brand/Topic)
    |
    v
[Social Media Agent (GPT-5.2)]
    |
    +---> XTools ---> X (Twitter) API
    |                    |
    |                    +---> Search tweets
    |                    +---> Get metrics
    |
    +---> ReasoningTools ---> Think/Analyze
    |
    v
SocialMediaReport (Structured Output)
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model
- `tweepy` - X API client (via XTools)

## API Credentials

To use this agent, you need X (Twitter) API credentials:

1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Create a project and app
3. Generate Bearer Token or OAuth credentials
4. Set environment variables as shown above
