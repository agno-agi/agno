# Llama Tutor

**Llama Tutor** is an intelligent educational assistant that provides personalized tutoring across all education levels.
It adapts explanations to your specific education level and uses real-time search to provide accurate, up-to-date information.

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/llama_tutor/requirements.txt
```

### 3. Configure API Keys

Required:

```bash
export GROQ_API_KEY=your_groq_key_here
export EXA_API_KEY=your_exa_key_here
```

Optional (for additional models):

```bash
export OPENAI_API_KEY=your_openai_key_here
export ANTHROPIC_API_KEY=your_anthropic_key_here
export GOOGLE_API_KEY=your_google_key_here
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
  agno/pgvector:16
```

### 5. Run the App

```shell
streamlit run cookbook/examples/streamlit_apps/llama_tutor/app.py
```

- Open [localhost:8501](http://localhost:8501) to view your app.

### Features

- **Education Level Adaptation**: Customizes explanations for Elementary, Middle School, High School, College, Undergrad, and Graduate levels
- **Real-time Search**: Uses DuckDuckGo and Exa for current information
- **Interactive Learning**: Provides examples, analogies, and comprehension questions
- **File Export**: Save educational content for future reference
- **Source Citations**: All facts and statistics include proper citations
- **Session Management**: Maintain conversation history across sessions

### How to Use

1. **Select Education Level**: Choose your appropriate education level from the sidebar
2. **Choose a Model**: Select from available AI models
3. **Ask Questions**: Type any educational question you'd like to learn about
4. **Get Personalized Answers**: Receive explanations tailored to your education level
5. **Save Content**: Export educational content as markdown files
6. **Continue Learning**: Ask follow-up questions to deepen understanding

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)