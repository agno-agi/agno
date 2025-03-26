# Gemini Tutor: Advanced Educational AI Assistant

Gemini Tutor is a powerful educational AI assistant powered by Google's Gemini 2.5 Pro Experimental, offering:

- 🧠 Advanced reasoning and thinking capabilities for complex problems
- 🔢 Expert at math, science, and coding challenges
- 📊 1 million token context window for comprehensive understanding
- 🎨 Visual explanations and diagrams
- 🖼️ Multimodal learning with image, audio, and video analysis
- 🔍 Real-time information retrieval
- 📚 Personalized learning experiences
- 💾 Save lessons for future reference

## Features

- **Advanced Reasoning**: Leverages Gemini 2.5 Pro's state-of-the-art thinking capabilities
- **Step-by-Step Problem Solving**: Breaks down complex concepts with detailed explanations
- **Visual Learning**: Generates visual explanations and diagrams to aid understanding
- **Multimodal Analysis**: Processes images, audio, and video for rich educational experiences
- **Code Generation**: Creates well-structured, executable code examples and challenges
- **Real-time Information**: Uses DuckDuckGo and Exa for up-to-date information
- **Personalized Experience**: Adapts to different education levels
- **Interactive Learning**: Includes practice questions and assessments
- **Session Management**: Save and organize your learning sessions

## Tech Stack

- 🤖 Gemini 2.5 Pro Experimental (March 2025) from Google
- 🚀 Agno framework for AI agents
- 💫 Streamlit for the UI
- 🔍 DuckDuckGo and Exa for search
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

4. Run Gemini Tutor:

```bash
streamlit run app.py
```

## Usage

1. Select your education level in the sidebar
2. Upload images, audio, or video files for analysis (optional)
3. Ask any question in the chat interface
4. Receive comprehensive answers with:
   - Clear explanations
   - Step-by-step reasoning
   - Visual aids
   - Code examples
   - Practice questions
   - Further reading suggestions
5. Save lessons for future reference
6. Manage your learning sessions

## Features in Detail

### Advanced Reasoning

- Complex problem-solving in math, science, and coding
- Step-by-step explanations with thinking process
- Logical reasoning
- Critical thinking exercises

### Multimodal Learning

- Upload and analyze images (diagrams, charts, photos)
- Process audio content for learning
- Analyze video material for educational insights
- Rich multimedia educational experiences

### Visual Learning

- Generated diagrams
- Visual explanations
- Interactive visualizations
- Concept maps

### Code Education

- Clean, well-commented code examples
- Interactive coding challenges
- Debugging assistance
- Best practices explanation

### Personalized Experience

- Adapts to education level
- Customized examples
- Level-appropriate language
- Progressive difficulty

### Interactive Elements

- Practice questions
- Self-assessment
- Progress tracking
- Engagement features

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
