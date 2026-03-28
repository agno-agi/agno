# GTM B2B Outreach Multi-Agent System

A powerful multi-agent system that automates B2B outreach by finding target companies, identifying decision-makers, researching insights, and generating personalized emails. Built with AI agents using OpenAI GPT models and Exa search capabilities.

---

## 🚀 Features

- **Company Discovery**: AI-powered search to find companies matching your targeting criteria
- **Contact Identification**: Automatically discovers decision-makers and key contacts
- **Phone Number Research**: Finds phone numbers for identified contacts
- **Company Research**: Gathers insights from websites and Reddit discussions
- **Email Generation**: Creates personalized outreach emails in multiple styles
- **Interactive Dashboard**: Streamlit-based web interface for easy operation

---

## 🏗️ Architecture

The system consists of 5 specialized AI agents working in sequence:

- **CompanyFinderAgent**: Discovers target companies using Exa search
- **ContactFinderAgent**: Identifies decision-makers and contacts
- **PhoneFinderAgent**: Researches phone numbers for contacts
- **ResearchAgent**: Collects company insights and intelligence
- **EmailWriterAgent**: Generates personalized outreach emails

---

## 📋 Prerequisites

- Python 3.8+
- OpenAI API key
- Exa API key

---

## 🛠️ Installation

1. Clone the repository
   ```bash
   git clone <repository-url>
   cd agno/cookbook/examples/streamlit_apps/gtm_outreach
   ```

2. Create a virtual environment
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies
   ```bash
   # Option 1: Install from requirements.txt
   pip install -r requirements.txt

   # Option 2: Generate fresh requirements (requires pip-tools)
   chmod +x generate_requirements.sh
   ./generate_requirements.sh
   pip install -r requirements.txt
   ```

---

## 🔑 API Keys Setup

### OpenAI API Key
1. Visit [OpenAI Platform](https://platform.openai.com/)
2. Create an account or sign in
3. Go to API Keys section
4. Create a new API key

### Exa API Key
1. Visit [Exa](https://exa.ai/)
2. Sign up for an account
3. Get your API key from the dashboard

### Environment Variables (Optional)
```bash
export OPENAI_API_KEY="your_openai_key_here"
export EXA_API_KEY="your_exa_key_here"
```

---

## 🚀 Usage

### Starting the Application
```bash
streamlit run app.py
```
The application will open in your browser at [http://localhost:8501](http://localhost:8501)

### Using the Interface
1. **Configure API Keys**: Enter your OpenAI and Exa API keys in the sidebar
2. **Define Target Companies**: Describe your ideal customer profile
3. **Describe Your Offering**: Explain what you're selling/offering
4. **Set Parameters**:
   - Your name and company
   - Calendar link (optional)
   - Number of companies (1-10)
   - Email style (Professional, Casual, Cold, Consultative)
5. Click **"Start Outreach"** to begin the automated process

### Email Styles
- **Professional**: Clear, respectful, and businesslike tone
- **Casual**: Friendly, approachable, first-name basis
- **Cold**: Strong hook with tight value proposition
- **Consultative**: Insight-led approach with soft call-to-action

---

## 📊 Output

The system provides comprehensive results:

- **Companies**: List of target companies with fit reasoning
- **Contacts**: Decision-makers with titles and email addresses
- **Phone Numbers**: Contact phone numbers with verification status
- **Research Insights**: Key intelligence about each company
- **Personalized Emails**: Ready-to-send outreach emails

---

## 🏃‍♂️ Example Workflow

```python
# Example target description
target_desc = """
SaaS companies with 50-200 employees in the fintech space,
particularly those focused on payment processing or digital banking
"""

# Example offering
offering_desc = """
AI-powered fraud detection solution that reduces false positives
by 40% while maintaining 99.9% accuracy in fraud detection
"""
```

---

## 📁 Project Structure

```
gtm-b2b-outreach/
├── app.py                    # Streamlit web application
├── agent.py                  # Agent definitions and pipeline functions
├── requirements.in           # Input requirements
├── requirements.txt          # Pinned dependencies
├── generate_requirements.sh  # Requirements generation script
└── README.md                # This file
```

---

## 🔧 Core Dependencies

- [agno](https://github.com/agency-swarm/agno): Multi-agent framework
- [streamlit](https://streamlit.io/): Web interface
- [openai](https://openai.com/): GPT model integration
- [exa_py](https://exa.ai/): Web search capabilities
- [pydantic](https://pydantic.dev/): Data validation

---

## 🛠️ Customization

### Adding New Email Styles
```python
def get_email_style_instruction(style_key: str) -> str:
    styles = {
        "Professional": "Style: Professional. Clear, respectful, and businesslike.",
        "YourStyle": "Your custom style instruction here.",
    }
    return styles.get(style_key, styles["Professional"])
```

### Modifying Agent Instructions
Each agent can be customized by updating the `instructions` parameter in the respective `create_*_agent()` functions.

### Adjusting Model Selection
```python
model=OpenAIChat(id="gpt-4")  # or "gpt-3.5-turbo"
```

---

## ⚠️ Important Notes

- **Rate Limits**: Be mindful of API rate limits for both OpenAI and Exa
- **Costs**: Monitor usage as API calls incur costs
- **Data Privacy**: Ensure compliance with data protection regulations
- **Email Deliverability**: Generated emails should be reviewed before sending

---

## 🐛 Troubleshooting

### Common Issues

- **API Key Errors**: Verify keys are correct and have sufficient credits. Check environment variable names.
- **JSON Parsing Errors**: The system includes fallback JSON extraction. Check agent instructions for proper JSON formatting.
- **No Results Found**: Refine your target company description. Try broader search criteria.
- **Streamlit Issues**: Clear browser cache. Restart the application. Check console for errors.

---

## 📈 Performance Tips

- Start with fewer companies (3-5) for testing
- Use specific targeting criteria for better results
- Review and refine generated content before use
- Monitor API usage and costs