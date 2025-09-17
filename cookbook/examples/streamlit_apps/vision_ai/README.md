# Vision AI Agent

**Vision AI** is a smart image analysis application that combines computer vision with large language models to provide intelligent visual understanding and interactive Q&A about images.
It allows users to upload images, get comprehensive analysis, and ask follow-up questions with session persistence and chat history.

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/vision_ai/requirements.txt
```

### 3. Configure API Keys

Required:

```bash
export OPENAI_API_KEY=your_openai_key_here
```

Optional (for additional models):

```bash
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
export GROQ_API_KEY=your_groq_key_here
```

### 4. Run PgVector

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/scripts/run_pgvector.sh
```

- OR run using the docker run command

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

### 5. Run Vision AI App

```shell
streamlit run cookbook/examples/streamlit_apps/vision_ai/app.py
```

## 🔧 Customization

### Model Selection

The application supports multiple model providers:

- OpenAI (gpt-4o, o3-mini)
- Anthropic (claude-4-sonnet)
- Google (gemini-2.5-pro)
- Groq (llama-3.3-70b-versatile)

### How to Use

- Open [localhost:8501](http://localhost:8501) in your browser.
- Upload an image (PNG, JPG, JPEG) for analysis.
- Choose analysis mode: Auto, Manual, or Hybrid.
- Get comprehensive image analysis results.
- Ask follow-up questions using the chat interface.
- Sessions are automatically saved with chat history.

### Troubleshooting

- **Docker Connection Refused**: Ensure `pgvector` containers are running (`docker ps`).
- **OpenAI API Errors**: Verify that the `OPENAI_API_KEY` is set and valid.
- **Image Upload Issues**: Check file format (PNG, JPG, JPEG) and size limits.

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)