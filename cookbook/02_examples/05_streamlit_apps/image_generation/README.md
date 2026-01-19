# Recipe Image Generator 🍳

A Streamlit application that transforms recipes into visual step-by-step cooking guides. Upload your own recipe PDFs or use the built-in Thai recipe collection, then ask for any recipe and receive detailed instructions with generated cooking images.

---

## 🚀 Setup Instructions

> Note: Fork and clone the repository if needed.

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate  
# On Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/streamlit_apps/image_generation/requirements.txt
```

### 3. Export API Keys

This app requires OpenAI API access for both language models and image generation:

```shell
export OPENAI_API_KEY=***       
```

### 4. Setup Database (Optional but Recommended)

The app uses PostgreSQL with pgvector for knowledge base storage:

```shell
# Using Docker
docker run -d \
  --name pgvector-db \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  phidata/pgvector:16
```

Or update the `db_url` in `agents.py` to use your existing PostgreSQL instance.

### 5. Run the Recipe Image Generator

```shell
streamlit run cookbook/examples/streamlit_apps/image_generation/app.py
```

- Open [http://localhost:8501](http://localhost:8501) in your browser to view the app.

## 🎯 Features

- **Recipe Upload**: Upload PDF files containing your favorite recipes
- **Default Collection**: Built-in Thai recipe collection for immediate use
- **Visual Generation**: Creates step-by-step cooking images showing the entire process
- **Knowledge Base**: Vector-powered recipe search and retrieval
- **Session Management**: Save and resume cooking conversations
- **Export Functionality**: Download chat history with recipes and images

## 🛠 How to Use

1. **Select Model**: Choose your preferred AI model from the sidebar dropdown
2. **Load Recipes**: Upload your own PDF files
3. **Try Sample Recipes**: Use the quick buttons for Pad Thai, Som Tum, Massaman Curry, or Tom Kha Gai
4. **Custom Requests**: Type natural language requests like:
   - "Recipe for Pad Thai with visual steps"
   - "Show me how to make a vegetarian curry"
   - "I want a quick 30-minute Thai recipe"
5. **View Results**: Get formatted ingredient lists, step-by-step directions, and cooking images
6. **Continue Conversation**: Ask follow-up questions or request recipe modifications

## 📚 Documentation

For more detailed information:

- [Agno Documentation](https://docs.agno.com)
- [Streamlit Documentation](https://docs.streamlit.io)

## 🤝 Support

Need help? Join our [Discord community](https://agno.link/discord)
