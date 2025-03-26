# Multimodal Learning Tutor

Multimodal Learning Tutor is a powerful educational AI assistant powered by Google's Gemini 2.5 Pro Experimental, offering comprehensive learning through multiple modalities:

## Multimodal Capabilities

- 🖼️ **Image Analysis**: Process diagrams, charts, equations, and visual content
- 🔊 **Audio Processing**: Extract knowledge from lectures, podcasts, and spoken explanations
- 🎬 **Video Analysis**: Learn from educational videos, demonstrations, and presentations
- 🔄 **Cross-Modal Learning**: Combine multiple types of media for enhanced understanding

## Advanced Search & Information

- 🔍 **Google Search**: Comprehensive web results for broad context and current events
- 📚 **Exa Search**: Academic and structured educational content for reliable information
- 🦆 **DuckDuckGo**: Additional search perspectives for balanced information
- 📊 **Multi-source Validation**: Cross-references information from multiple sources for accuracy

## Advanced AI Features

- 🧠 Advanced reasoning and thinking capabilities for complex problems
- 💭 Visible step-by-step reasoning process that shows its thinking
- 🤖 Agentic AI capabilities to complete multi-step educational tasks
- 🔢 Expert at math, science, and coding challenges
- 📊 1 million token context window for comprehensive understanding
- 📚 Personalized learning experiences
- 💾 Save lessons for future reference

## Educational Features

- **Advanced Reasoning Modes**: Choose between standard responses or detailed thinking processes
- **Step-by-Step Problem Solving**: Breaks down complex concepts with detailed explanations
- **Visual Learning**: Generates visual explanations and diagrams to aid understanding
- **Comprehensive Research**: Uses multiple search engines for thorough, balanced information
- **Personalized Experience**: Adapts to different education levels from elementary to PhD
- **Interactive Learning**: Includes practice questions and assessments
- **Session Management**: Save and organize your learning sessions

## Tech Stack

- 🤖 Gemini 2.5 Pro Experimental (March 2025) from Google
- 🚀 Agno framework for AI agents
- 💫 Streamlit for the UI
- 🔍 Multiple search engines (Google Search, DuckDuckGo, Exa)
- 💾 File system for saving lessons

## Setup

1. Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure API Keys:
   Create a `.env` file with your API keys:

```
GOOGLE_API_KEY=your_gemini_api_key_here
EXA_API_KEY=your_exa_api_key_here
```

4. Run Multimodal Learning Tutor:

```bash
streamlit run app.py
```

## Usage

1. Select your education level in the sidebar (Elementary through PhD)
2. Choose your preferred reasoning mode (Standard or Thinking)
3. Select the Gemini model to use (recommended: Gemini 2.5 Pro Experimental)
4. **Upload media for analysis**:
   - Images: Diagrams, charts, problems, or any visual content
   - Audio: Lectures, explanations, or other audio content
   - Video: Educational videos or demonstrations
5. Use suggested prompts or ask custom questions about the uploaded media
6. Receive comprehensive answers with:
   - Clear explanations of the multimodal content
   - Step-by-step reasoning
   - Visual aids
   - Code examples when relevant
   - Practice questions
   - Further reading suggestions
7. Save lessons for future reference
8. Manage your learning sessions

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
