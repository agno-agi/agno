# Paperpal Research Assistant

**Paperpal** is a research and technical blog writer workflow that writes a detailed blog on research topics referencing research papers by utilizing models and external tools: Exa and ArXiv

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/paperpal/requirements.txt
```

### 3. Configure API Keys

Required:

```bash
export OPENAI_API_KEY=your_openai_key_here
export EXA_API_KEY=your_exa_key_here
```

Optional (for additional models):

```bash
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
export GROQ_API_KEY=your_groq_key_here
```

### 4. Run the Application

```shell
streamlit run cookbook/examples/streamlit_apps/paperpal/app.py
```
### Research Workflow

1. **Topic Definition**: Enter your research topic or select from trending topics
2. **Configuration**: Choose research sources (ArXiv, Web) and parameters
3. **Search Term Generation**: AI creates strategic search terms
4. **Content Analysis**: AI selects and analyzes most relevant sources
5. **Blog Synthesis**: Generation of comprehensive technical blog with citations

### Supported Research Areas

- **Artificial Intelligence & Machine Learning**
- **Computer Science & Software Engineering** 
- **Data Science & Analytics**
- **Emerging Technologies**
- **Healthcare & Biotechnology**
- **Physics & Engineering**
- **Cross-disciplinary Research**

### Research Configuration
- **Academic Focus**: Enable ArXiv search for peer-reviewed papers
- **Industry Focus**: Enable web search for current developments
- **Comprehensive**: Use both sources for complete coverage
- **Search Terms**: 2-3 terms for balanced coverage vs. speed


## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)