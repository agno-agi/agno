# LLM OS

Lets build the LLM OS

## The LLM OS design:

<img alt="LLM OS" src="https://github.com/agno-agi/agno/assets/22579644/5cab9655-55a9-4027-80ac-badfeefa4c14" width="600" />

- LLMs are the kernel process of an emerging operating system.
- This process (LLM) can solve problems by coordinating other resources (memory, computation tools).
- The LLM OS:
  - [x] Can read/generate text
  - [x] Has more knowledge than any single human about all subjects
  - [x] Can browse the internet (e.g., using DuckDuckGo)
  - [x] Can use existing software infra (calculator, python, shell)
  - [ ] Can see and generate images and video
  - [ ] Can hear and speak, and generate music
  - [ ] Can think for a long time using a system 2
  - [ ] Can "self-improve" in domains
  - [ ] Can be customized and fine-tuned for specific tasks
  - [x] Can communicate with other LLMs

[x] indicates functionality that is implemented in this LLM OS app

## Running the LLM OS:

> Note: Fork and clone this repository if needed


### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/llmos
source ~/.venvs/llmos/bin/activate
```

### 2. Install libraries

install the packages:
```shell
pip install -r cookbook/examples/apps/llm_os_v2/requirements.txt
```


### 3. Export credentials

```shell
# Option 2: Export environment variable
export OPENAI_API_KEY=sk-your-key-here
```

### 4. Run the LLM OS App

The application uses SQLite for session storage (`llm_os_sessions.db`), so no external database setup (like PgVector or Qdrant) is needed for basic operation.

```shell
streamlit run cookbook/examples/apps/llm_os_v2/app.py
```

- Open [localhost:8501](http://localhost:8501) to view your LLM OS.
- Try some examples:
    - Add knowledge (if supported): Add information from this blog post: https://blog.samaltman.com/gpt-4o
    - Ask: What is gpt-4o?
    - Web search: What is happening in france?
    - Calculator: What is 10!
    - Enable shell tools and ask: Is docker running?
    - Ask (if Research tool enabled): Write a report on the ibm hashicorp acquisition
    - Ask (if Investment tool enabled): Shall I invest in nvda?
