# Medical Imaging Analysis

**Medical Imaging Analysis** Agent is a medical imaging analysis agent that analyzes medical images and provides detailed findings by utilizing models and external tools.

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/medical_imaging/requirements.txt
```

### 3. Configure API Keys

Required:

```bash
export GOOGLE_API_KEY=your_google_key_here
```

Optional (for additional models):

```bash
export OPENAI_API_KEY=your_openai_key_here
export ANTHROPIC_API_KEY=your_anthropic_key_here
```

### 4. Run the Application

```shell
streamlit run cookbook/examples/streamlit_apps/medical_imaging/app.py
```

### 📚 Educational Support
- Sample questions for learning
- Medical imaging guidance
- Best practices and standards


### Usage Examples

1. **Upload a medical image** using the sidebar file uploader
2. **Add clinical context** such as patient history or symptoms
3. **Receive comprehensive analysis** with professional insights
4. **Ask follow-up questions** for clarification or additional details
5. **Export results** for documentation or further review

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)