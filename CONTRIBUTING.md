# Contributing to agno

Agno is an open-source project and we welcome contributions.

## 👩‍💻 How to contribute

Please follow the [fork and pull request](https://docs.github.com/en/get-started/quickstart/contributing-to-projects) workflow:

- Fork the repository.
- Create a new branch for your feature.
- Add your feature or improvement.
- Send a pull request.
- We appreciate your support & input!


## Development setup

1. Clone the repository.
2. Check if you have `uv` installed by running `uv --version`.
   - If you have `uv` installed, you can skip this step.
   - If you don't have `uv` installed, you can install it by running `pip install uv`.
3. Create a virtual environment:
   - For Unix, use `./scripts/dev_setup.sh`.
   - For Windows, use `.\scripts\dev_setup.bat`.
   - This setup will:
     - Create a `.venv` virtual environment in the current directory.
     - Install the required packages.
     - Install the `agno` package in editable mode.
4. Activate the virtual environment:
   - On Unix: `source .venv/bin/activate`
   - On Windows: `.venv\Scripts\activate`

> From here on you have to use `uv pip install` to install missing packages

## Formatting and validation

Ensure your code meets our quality standards by running the appropriate formatting and validation script before submitting a pull request:

- For Unix:
  - `./scripts/format.sh`
  - `./scripts/validate.sh`
- For Windows:
  - `.\scripts\format.bat`
  - `.\scripts\validate.bat`

These scripts will perform code formatting with `ruff` and static type checks with `mypy`.

## Local testing

Before submitting a pull request, ensure all tests pass locally:

1. Do the development setup above.

2. Run the test suite `./scripts/test.sh`

3. Run specific test files or test cases: `pytest ./libs/agno/tests/unit/utils/test_string.py` or whatever file you want to test.

Make sure all tests pass before submitting your pull request. If you add new features, include appropriate test coverage.

## Adding a new Vector Database

1. Setup your local environment by following the [Development setup](#development-setup).
2. Create a new directory under `libs/agno/agno/vectordb` for the new vector database.
3. Create a Class for your VectorDb that implements the `VectorDb` interface
   - Your Class will be in the `libs/agno/agno/vectordb/<your_db>/<your_db>.py` file.
   - The `VectorDb` interface is defined in `libs/agno/agno/vectordb/base
   - Import your `VectorDb` Class in `libs/agno/agno/vectordb/<your_db>/__init__.py`.
   - Checkout the [`libs/agno/agno/vectordb/pgvector/pgvector`](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/vectordb/pgvector/pgvector.py) file for an example.
4. Add a recipe for using your `VectorDb` under `cookbook/agent_concepts/knowledge/vector_dbs/<your_db>`.
   - Checkout [`cookbook/agent_concepts/knowledge/vector_dbs/pg_vector`](https://github.com/agno-agi/agno/blob/main/cookbook/agent_concepts/knowledge/vector_dbs/pg_vector.py) for an example.
5. Important: Format and validate your code by running `./scripts/format.sh` and `./scripts/validate.sh`.
6. Submit a pull request.

## Adding a new Model Provider

1. Setup your local environment by following the [Development setup](#development-setup).
2. Create a new directory under `libs/agno/agno/models` for the new Model provider.
3. If the Model provider supports the OpenAI API spec:
   - Create a Class for your LLM provider that inherits the `OpenAILike` Class from `libs/agno/agno/models/openai/like.py`.
   - Your Class will be in the `libs/agno/agno/models/<your_model>/<your_model>.py` file.
   - Import your Class in the `libs/agno/agno/models/<your_model>/__init__.py` file.
   - Checkout the [`agno/models/xai/xai.py`](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/models/together/together.py) file for an example.
4. If the Model provider does not support the OpenAI API spec:
   - Reach out to us on [Discord](https://discord.gg/4MtYHHrgA8) or open an issue to discuss the best way to integrate your LLM provider.
   - Checkout [`agno/models/anthropic/claude.py`](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/models/anthropic/claude.py) or [`agno/models/cohere/chat.py`](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/models/cohere/chat.py) for inspiration.
5. Add a recipe for using your Model provider under `cookbook/models/<your_model>`.
   - Checkout [`agno/cookbook/models/aws/claude`](https://github.com/agno-agi/agno/tree/main/cookbook/models/aws/claude) for an example.
6. Important: Format and validate your code by running `./scripts/format.sh` and `./scripts/validate.sh`.
7. Submit a pull request.

## Adding a new Tool.

1. Setup your local environment by following the [Development setup](#development-setup).
2. Create a new directory under `libs/agno/agno/tools` for the new Tool.
3. Create a Class for your Tool that inherits the `Toolkit` Class from `libs/agno/agno/tools/toolkit/.py`.
   - Your Class will be in `libs/agno/agno/tools/<your_tool>.py`.
   - Make sure to register all functions in your class via a flag.
   - Checkout the [`agno/tools/youtube_tools.py`](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/youtube_tools.py) file for an example.
   - If your tool requires an API key, checkout the [`agno/tools/serpapi_tools.py`](https://github.com/agno-agi/agno/blob/main/libs/agno/agno/tools/serpapi_tools.py) as well.
4. Add a recipe for using your Tool under `cookbook/tools/<your_tool>`.
   - Checkout [`agno/cookbook/tools/youtube_tools`](https://github.com/agno-agi/agno/blob/main/cookbook/tools/youtube_tools.py) for an example.
5. Important: Format and validate your code by running `./scripts/format.sh` and `./scripts/validate.sh`.
6. Submit a pull request.

Message us on [Discord](https://discord.gg/4MtYHHrgA8) or post on [Discourse](https://community.agno.com/) if you have any questions or need help with credits.

## 📚 Resources

- <a href="https://docs.agno.com/introduction" target="_blank" rel="noopener noreferrer">Documentation</a>
- <a href="https://discord.gg/4MtYHHrgA8" target="_blank" rel="noopener noreferrer">Discord</a>
- <a href="https://community.agno.com/" target="_blank" rel="noopener noreferrer">Discourse</a>

## 📝 License

This project is licensed under the terms of the [MPL-2.0 license](/LICENSE)
