# Gemini Multimodal Learning Tutor 📚🧠

Gemini Multimodal Learning Tutor is an advanced educational AI assistant powered by Google's Gemini 2.5 Pro Experimental. It provides personalized, interactive, and multimodal learning experiences tailored to various education levels.

---

## 🚀 Features

### Multimodal Capabilities

- 🖼️ **Image Analysis**: Interpret diagrams, charts, equations, and visual content.
- 🔊 **Audio Processing**: Extract insights from lectures, podcasts, and spoken explanations.
- 🎬 **Video Analysis**: Learn from educational videos, demonstrations, and presentations.
- 🔄 **Cross-Modal Learning**: Combine multiple media types for enhanced understanding.

### Advanced Search & Information

- 🔍 **Google Search**: Comprehensive web results for broad context and current events.
- 📚 **Exa Search**: Academic and structured educational content.
- 🦆 **DuckDuckGo**: Additional search perspectives for balanced information.
- 📊 **Multi-source Validation**: Cross-reference information from multiple sources.

### Advanced AI Features

- 🧠 Advanced reasoning for complex problems.
- 💭 Visible step-by-step reasoning.
- 🤖 Agentic AI for multi-step educational tasks.
- 🔢 Expert at math, science, and coding challenges.
- 📊 1 million token context window.
- 📚 Personalized learning experiences.
- 💾 Save lessons for future reference.

### Educational Features

- **Reasoning Modes**: Standard responses or detailed thinking processes.
- **Step-by-Step Problem Solving**: Detailed explanations of complex concepts.
- **Visual Learning**: Visual explanations and diagrams.
- **Interactive Learning**: Practice questions and assessments.
- **Session Management**: Save and organize learning sessions.

---

## 🛠️ Tech Stack

- 🤖 **Gemini 2.5 Pro Experimental** (March 2025) from Google
- 🚀 **Agno Framework** for AI agents
- 💫 **Streamlit** for interactive UI
- 🔍 **Multiple Search Engines** (Google, DuckDuckGo, Exa)
- 💾 **File System** for saving lessons

---

## ⚙️ Setup Instructions

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install requirements

```shell
pip install -r cookbook/examples/apps/gemini-tutor/requirements.txt
```

### 3. Export `GEMINI_API_KEY`

```shell
export GEMINI_API_KEY=***
```

### 4. Run Streamlit App

```shell
streamlit run cookbook/examples/apps/gemini-tutor/app.py
```

---

## 📂 Project Structure

## Multimodal Learning Features in Detail

### Image Analysis

- **Visual Problem Solving**: Analyze mathematical equations, diagrams, and problems
- **Chart and Graph Interpretation**: Extract data and insights from visual representations
- **Text in Images**: Recognize and interpret text within images
- **Spatial Reasoning**: Understand spatial relationships in visual content
- **Scientific Diagrams**: Interpret complex scientific visualizations

### Audio Analysis

- **Lecture Understanding**: Extract key concepts from educational audio
- **Speech Comprehension**: Process spoken explanations and instructions
- **Language Learning**: Analyze pronunciation and language patterns
- **Music Education**: Interpret musical concepts and theory
- **Sound Pattern Recognition**: Identify patterns in audio data

### Video Analysis

- **Tutorial Comprehension**: Extract step-by-step instructions from video tutorials
- **Demo Understanding**: Process demonstrations of concepts or experiments
- **Presentation Analysis**: Extract key points from educational presentations
- **Motion Analysis**: Understand physical processes shown in videos
- **Visual Storytelling**: Interpret narrative and sequential information

### Advanced Search Features

- **Multi-engine Search**: Leverages Google Search, Exa, and DuckDuckGo simultaneously
- **Information Synthesis**: Combines results from multiple sources for comprehensive answers
- **Current Events**: Access up-to-date information on recent developments
- **Academic Content**: Retrieve scholarly and educational resources
- **Source Credibility**: Cross-validate information across different search providers

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
