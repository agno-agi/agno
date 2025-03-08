# VisioAI 🖼️
VisioAI is a **smart image analysis agent** that extracts structured insights from images using AI-powered **object detection, OCR, and scene recognition**.

The system is designed with two separate agents:
- **Image Processing Agent**: Extracts structured insights based on the uploaded image and user instructions.
- **Chat Agent**: Answers follow-up questions using the last extracted insights and (optionally) web search via DuckDuckGo.

VisioAI allows users to interact with images in **Auto, Manual, and Hybrid modes**, offering a powerful and flexible workflow.

---

## 🚀 **Setup Instructions**

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install libraries

```shell
pip install -r cookbook/examples/apps/visio_ai/requirements.txt
```

### 3. Run PgVector

Let's use Postgres for storing our data, but the VisioAI Agent should work with any database.

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

### 4. Export API Keys

We recommend using gpt-4o for this task, but you can use any Model you like.

```shell
export OPENAI_API_KEY=***
```

Other API keys are optional, but if you'd like to test:

```shell
export GOOGLE_API_KEY=***
```

### 5. Run VisioAI Agent

```shell
streamlit run cookbook/examples/apps/visio_ai/app.py
```

- Open [localhost:8501](http://localhost:8501) to view the VisioAI Agent.

### 6. Features

### ✅ Multiple Image Processing Modes
- **Auto Mode**: Image is processed as soon as it's uploaded.
- **Manual Mode**: Users provide specific instructions before processing.
- **Hybrid Mode**: A mix of auto-processing and user-defined instructions.

### ✅ Chat Agent for Follow-Up Queries
- Ask follow-up questions based on extracted insights.
- Uses stored session history to improve responses.
- Supports **optional web search** using **DuckDuckGo**.

### ✅ Enable/Disable Web Search
- Users can toggle **web search (DuckDuckGo)** **on/off** using a **radio button** in the sidebar.
- If enabled, the chat agent uses **external search results** to enhance responses.

---

### 7. How to Use 🛠

- **Upload an Image**: Choose any **PNG, JPG, or JPEG** file.
- **Model Choice**: Choose whether you would like to use OpenAI or Gemini
- **Toggle Web Search**: Enable/disable external web search if needed.
- **Select Processing Mode**: Auto, Manual, or Hybrid.
- **Enter Instructions** *(if required for Manual/Hybrid Mode).*
- **Extract Insights**: The agent processes the image and extracts details.
- **Ask Follow-Up Questions**: Chat agent answers based on extracted insights.
- **Toggle Web Search**: Enable/disable external web search if needed.

### 8. Message us on [discord](https://agno.link/discord) if you have any questions


