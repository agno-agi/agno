## Installation

There are multiple setup options available as vLLM supports GPU and TPU acceleration. Here are all the installation options:

> https://docs.vllm.ai/en/latest/getting_started/installation/index.html

## Macbook setup - CPU 

### Create a virtual environment

```bash
uv venv --python 3.12 --seed
source .venv/bin/activate
```

### Install vLLM from source

```bash
git clone https://github.com/vllm-project/vllm.git
cd vllm
pip install -r requirements/cpu.txt
pip install -e .
```

## Examples

Serve the vLLM model:
```bash
vllm serve microsoft/Phi-3-mini-4k-instruct \
    --dtype float32 \
    --enable-auto-tool-choice \
    --tool-call-parser pythonic
```

Run the agent
```bash
python cookbook/models/vllm/basic.py
```

## Supported Models

### Text Generation models

Here are some of the text models vLLM supports: 

> https://docs.vllm.ai/en/stable/models/supported_models.html?h=models#generative-models

----

### Multi-modal models

Here are some multi-modal models vLLM supports:

> https://docs.vllm.ai/en/stable/models/supported_models.html?h=models#text-generation_1

---
## Loading HF models

By default, vLLM supports all models from Hugging Face (HF) Hub. Here's more details on setting them up and using them with Agno Agents

> https://docs.vllm.ai/en/stable/models/supported_models.html?h=models#loading-a-model