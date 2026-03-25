# 📝 Quiz Generator Agent

An intelligent educational assessment agent that automatically generates Multiple Choice Questions (MCQs) from any provided text content.

## 🎯 Purpose

The Quiz Generator Agent specializes in creating comprehensive educational assessments by:
- Analyzing provided text content
- Generating exactly 10 multiple-choice questions
- Providing 4 options per question (A, B, C, D)
- Including one-sentence explanations for correct answers
- Formatting output in clean markdown

## ✨ Features

- **Intelligent Question Generation**: Uses advanced AI to create relevant questions from any text
- **Structured Output**: Consistent 10-question format with clear formatting
- **Educational Focus**: Designed for professional teaching and assessment
- **Explanations**: Each question includes a brief explanation of the correct answer
- **Markdown Formatting**: Clean, readable output suitable for educational materials

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- OpenRouter API key

### Installation

1. **Clone/Download the agent files**
2. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env and add your OPENROUTER_API_KEY
   ```

3. **Install dependencies**:
   ```bash
   cd examples
   uv sync
   ```

4. **Run the agent**:
   ```bash
   uv run Quiz-Agent/main.py
   ```

5. **Access the interface**:
   Open http://localhost:3773 in your browser

## 📖 Usage

### Basic Usage
1. Start the agent
2. Provide any text content (article, chapter, notes, etc.)
3. Receive a complete 10-question MCQ quiz with explanations

### Example Input
```
The process of photosynthesis occurs in two stages. The first stage is the light-dependent reactions, which capture energy from sunlight. The second stage is the Calvin cycle, which uses that energy to produce glucose.
```

### Example Output
```markdown
# 📝 Quiz: Knowledge Check

---

### Question 1
What are the two stages of photosynthesis?
A) Light-dependent reactions and Calvin cycle
B) Respiration and glycolysis
C) Fermentation and oxidation
D) Synthesis and decomposition

**Correct Answer:** A
**Explanation:** Photosynthesis consists of light-dependent reactions that capture solar energy and the Calvin cycle that produces glucose.

---
(9 more questions follow)
```

## ⚙️ Configuration

The agent uses the following configuration:

```python
config = {
    "author": "your.email@example.com",
    "name": "quiz_generator_agent", 
    "description": "Educational assessment expert for MCQ generation",
    "deployment": {
        "url": "http://localhost:3773",
        "expose": True,
        "cors_origins": ["http://localhost:5173"]
    }
}
```

## 🔧 Technical Details

### Agent Architecture
- **Framework**: Bindu + Agno
- **Model**: OpenAI GPT-OSS-120B via OpenRouter
- **Processing**: Natural language understanding for educational content
- **Output**: Structured markdown format

### Key Components
- **Question Generation**: AI-powered analysis of input text
- **Option Creation**: Intelligent distractor generation
- **Answer Validation**: Ensuring single correct answer per question
- **Explanation Generation**: Concise educational explanations

## 🎓 Educational Applications

- **Classroom Assessment**: Quick quiz generation for lessons
- **Study Materials**: Create practice tests from textbooks
- **Content Validation**: Test understanding of written materials
- **E-Learning**: Automated quiz generation for online courses
- **Professional Development**: Assessment tools for training programs

## 🔒 Environment Variables

Required environment variables:

```bash
OPENROUTER_API_KEY=sk-or-v1-your-api-key-here
```

Optional infrastructure variables (auto-configured):

```bash
# Storage (default: memory)
DATABASE_URL=postgresql+asyncpg://user:pass@host/db

# Scheduler (default: memory)  
REDIS_URL=rediss://default:pass@host:6379

# Bindu Authentication
HYDRA__ADMIN_URL=https://hydra-admin.getbindu.com
HYDRA__PUBLIC_URL=https://hydra.getbindu.com
```

## 🧪 Testing

### Interactive Testing
1. Start the agent: `uv run rajat/main.py`
2. Visit http://localhost:3773/docs
3. Test with various text inputs

### Example Test Cases
- Scientific articles
- Historical texts  
- Literary passages
- Technical documentation
- News articles

## 📊 Output Format

The agent consistently produces:
- **Title**: "📝 Quiz: Knowledge Check"
- **Questions**: Exactly 10 MCQs
- **Options**: A, B, C, D format
- **Answers**: Clearly marked correct answers
- **Explanations**: One-sentence justifications
- **Separators**: Markdown dividers between questions

## 🔄 API Usage

### Direct API Call
```bash
curl -X POST http://localhost:3773/ \
     -H "Content-Type: application/json" \
     -d '{
           "jsonrpc": "2.0",
           "method": "message/send",
           "params": {
             "message": {
               "role": "user", 
               "content": "Your text content here..."
             }
           },
           "id": 1
         }'
```

## 🛠️ Development

### Customization
To modify the agent behavior:
1. Edit `main.py`
2. Adjust the `instructions` parameter for different question types
3. Modify `expected_output` for alternative formatting
4. Change model selection in `OpenRouter` configuration

### Extending Functionality
- Add different question types (True/False, Fill-in-blank)
- Implement difficulty levels
- Add subject-specific question templates
- Include scoring mechanisms

## 📝 License

This agent is part of the Bindu Examples Gallery and follows the same license terms as the parent project.

## 🤝 Contributing

Contributions welcome! Please:
1. Test thoroughly with various content types
2. Ensure educational appropriateness
3. Maintain consistent output format
4. Update documentation

---

**🌻 Built with Bindu Framework**

*Identity + Communication + Payments for AI Agents*
