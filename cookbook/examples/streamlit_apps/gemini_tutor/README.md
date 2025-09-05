# Gemini Tutor

An advanced educational AI assistant powered by Google's Gemini models that creates personalized, multimodal learning experiences. This example demonstrates how to build sophisticated educational applications with adaptive content delivery and interactive learning elements.

## ✨ Features

- **🧠 Educational AI**: Powered by Google's Gemini 2.5 Pro with educational expertise
- **📚 Adaptive Learning**: Content automatically adapts to different education levels
- **🔍 Research Integration**: Real-time search for up-to-date educational content

- **💾 Session Management**: Save and resume learning sessions
- **🎓 Multi-Level Support**: From Elementary School to PhD level content

## 🚀 Quick Start

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/gemini_tutor/requirements.txt
```

### 3. Export API Keys

Set up your Google API key for Gemini models:

```shell
# Required for Gemini models
export GOOGLE_API_KEY=***
```

### 4. Run the Tutor

```shell
streamlit run cookbook/examples/streamlit_apps/gemini_tutor/app.py
```

Open [localhost:8501](http://localhost:8501) to start your learning session.

## 🎓 How It Works

### 📚 Learning Experience Structure

Each learning session includes:

- **Introduction**: Overview and learning objectives
- **Core Concepts**: Key ideas explained at appropriate level  
- **Examples & Applications**: Relevant, relatable examples
- **Interactive Elements**: Thought experiments and practical exercises
- **Assessment**: Practice questions with detailed answers
- **Summary**: Key takeaways and next steps

### 🎯 Education Level Adaptation

Content is automatically adapted for:

- **Elementary School**: Simple language, basic concepts, visual analogies
- **High School**: Intermediate complexity, real-world applications
- **College**: Advanced concepts, theoretical frameworks
- **Graduate**: Research-level depth, critical analysis
- **PhD**: Expert-level discussions, cutting-edge research

## 🎮 Learning Templates

### Quick Learning Modules

- **🔬 Science Concepts**: Interactive science explanations with experiments
- **📊 Math Problem Solving**: Step-by-step mathematical problem solving
- **🌍 History & Culture**: Historical events and cultural analysis
- **💻 Technology & Programming**: Technical concepts with hands-on examples


## 💡 Usage Examples

### Basic Learning Session
```python
# Ask about any topic
"Explain quantum physics for high school students"
"How does photosynthesis work?"
"Teach me calculus derivatives with examples"
```

### Interactive Learning
```python
# Request specific learning structures
"Create a complete learning module about the Renaissance with practice questions"
"Explain machine learning with thought experiments for college level"
"Give me a study guide for organic chemistry"
```

### Assessment & Practice
```python
# Generate practice materials
"Create a practice quiz on what we just learned"
"Give me word problems for algebra practice" 
"Test my understanding of the periodic table"
```
## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)