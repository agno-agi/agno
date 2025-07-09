# Content Creator Agent Workflow

The Content Creator Agent Workflow is a multi-agent workflow designed to streamline the process of generating and managing social media content. It assists content creators in planning, creating, and scheduling posts across various platforms.

## Key Features

- **Scraping Blog Posts:** Scrape a blog post and convert it to understandable draft.

- **Automated Content Generation:** Draft engaging posts tailored to your audience.

- **Scheduling and Management:** Allows for efficient scheduling of posts, ensuring a consistent online presence.

- **Platform Integration:** Supports multiple social media platforms for broad outreach (Linkedin and X).

## Getting Started

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/agno-agi/agno.git
   ```

2. **Navigate to the Workflow Directory:**

   ```bash
   cd agno/workflows/content-creator-workflow
   ```

3. **Create Virtual Environment**

  ```bash
  python3 -m venv ~/.venvs/aienv
  source ~/.venvs/aienv/bin/activate
  ```

4. **Install Dependencies:**

   Ensure you have Python installed, then run:

   ```bash
   pip install -r requirements.txt
   ```

5. **Set the Environment Variables**

    ```bash
    export OPENAI_API_KEY="your_openai_api_key_here"
    export FIRECRAWL_API_KEY="your_firecrawl_api_key_here"
    export TYPEFULLY_API_KEY="your_typefully_api_key_here"
    ```

    These keys are used to authenticate requests to the respective APIs.

6. **Configure the Workflow**

    The `config.py` file is used to centralize configurations for your project. It includes:

    - **API Configuration**:
        - Defines the base URLs and headers required for API requests, with keys loaded from the `.env` file.
    - **Enums**:
        - `PostType`: Defines the type of social media posts, such as `TWITTER` or `LINKEDIN`.

    Update the `.env` file with your API keys and customize the enums in `config.py` if additional blog URLs or post types are needed.


7. **Run the Workflow:**

   Execute the main script to start the content creation process:

   ```bash
   python workflow.py
   ```

## Customization

The workflow is designed to be flexible. You can adjust the model provider parameters, content templates, and scheduling settings within the configuration files to better suit your needs.
