# Universal Agent Interface

The Universal Agent Interface is a multi-modal interface for interacting with multiple agents using a single entrypoint. It is built on top of the LLM OS.

The LLM OS was proposed by Andrej Karpathy 18 months ago [in this tweet](https://twitter.com/karpathy/status/1723140519554105733), [this tweet](https://twitter.com/karpathy/status/1707437820045062561) and [this video](https://youtu.be/zjkBMFhNj_g?t=2535). I built an early prototype of the LLM OS in 2024 (checkout this [video](https://x.com/ashpreetbedi/status/1790109321939829139)), which has now evolved into the Universal Agent Interface.

## Notes:
- This is a beta release and I am still porting over the internal agent to the public repo. I'm not even sure if people will like this so im not spending too much time on a polished UI.
- This is a work in progress. Not everything is tested, stuff will break. Please submit a PR to improve the code.
- Again: please don't expect this to work as expected. It's a work in progress.

## The Universal Agent Interface design:

- UAgI is a single interface for orchestrating multiple agents.
- UAgI solves problems by "thinking" about the intent, then coordinating other agents to solve the problem, and finally, "analyzes" the results. It can then re-plan and re-execute as needed.
- UAgI capabilities:
  - [x] Can read/generate text
  - [x] Has more knowledge than any single human about all subjects
  - [x] Can browse the internet (e.g., using DuckDuckGo)
  - [x] Can use existing software infra (calculator, python, shell)
  - [-] Can see and generate images and video
  - [ ] Can hear and speak, and generate music
  - [ ] Can think for a long time using a system 2
  - [-] Can "self-improve" in domains
  - [ ] Can be customized and fine-tuned for specific tasks
  - [x] Can communicate with other Agents

[x] indicates functionality that is implemented in this UAgI app

## Pending Updates:

- [ ] Stream member agent responses. This is possible but we just haven't ported it over yet.
- [ ] Image and video input/output. This is possible but we just haven't ported it over yet.
- [ ] Self-improvement using auto-updating knowledge and dynamic few-shot. This is possible but we just haven't ported it over yet.

## Running the UAgI:

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

Create a virtual environment using [uv](https://docs.astral.sh/uv/getting-started/installation/) and activate it:

```shell
uv venv .uagi-env --python 3.12
source .uagi-env/bin/activate
```

### 2. Install dependencies

```shell
uv pip install -r cookbook/examples/apps/universal_agent_interface/requirements.txt
```

### 3. Export credentials

We'll use 3.7 sonnet and gpt-4o-mini for UAgI
- 3.7 sonnet for the main UAgI agent
- gpt-4o-mini for smaller tasks

```shell
export ANTHROPIC_API_KEY=***
export OPENAI_API_KEY=***
```

### 4. Run the Universal Agent Interface

The application uses SQLite for session storage (`uagi_sessions.db`), so no external database setup (like PgVector or Qdrant) is needed for basic operation.

```shell
streamlit run cookbook/examples/apps/universal_agent_interface/app.py
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