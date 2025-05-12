# Recipe Image Generator 🍳

Recipe Image Generator is an interactive Streamlit application that leverages Agno to generate step-by-step cooking images from recipes. Upload your own recipe PDF or use the built-in sample recipe book, then ask for a recipe (e.g., "Recipe for Pad Thai") and watch the app generate visual cooking instructions.


---

## 🚀 Setup Instructions

> Note: Fork and clone the repository if needed.

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```shell
pip install -r cookbook/examples/apps/image_generation/requirements.txt
```

### 3. Export API Keys

This app uses the Llama family of models offer via Groq

```shell
export GROQ_API_KEY=***       # for Groq models
```

### 4. Run the Recipe Image Generator

```shell
streamlit run cookbook/examples/apps/image_generation/app.py
```

- Open [http://localhost:8501](http://localhost:8501) in your browser to view the app.

---

## 🎯 Features

- **Recipe Upload**: Upload a PDF of your favorite recipes or use the default sample recipe book.
- **Interactive Chat**: Ask for a recipe by name and receive a streamed, step-by-step visual guide.
- **Example Recipes**: Quick-start buttons for common recipes like Pad Thai, Som Tum, Massaman Curry, and Tom Kha Gai.
- **Tool Call Visualization**: View intermediate tool calls and results within the chat interface.
- **Image Rendering**: Inline display of generated images or fallback on URLs.

---

## 🛠 How to Use

1. **Select Model**: Use the sidebar dropdown to pick a model.
2. **Load Recipes**: Click "Load recipes" (optional) to preload sample recipes.
3. **Try Examples**: Click an example recipe in the sidebar under "Try an example recipe".
4. **Upload PDF**: Upload your own recipe PDF file or check "Use default sample recipe book".
5. **Chat**: Type your request in the chat input (e.g., "Recipe for Pad Thai").
6. **View Images**: Scroll through the chat to see the generated images and instructions.

---

## 💬 Support

Join our [Discord community](https://agno.link/discord) for questions and discussion.

