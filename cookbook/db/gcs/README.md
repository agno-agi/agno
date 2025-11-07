# Google Cloud Storage Integration

Examples demonstrating Google Cloud Storage (GCS) integration with Agno agents using JSON blob storage.

## Setup

```shell
pip install google-cloud-storage
```

## Configuration

```python
from agno.agent import Agent
from agno.storage.gcs_json import GCSJsonDb

db = GCSJsonDb(
    bucket_name="your-bucket-name",
)

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Authentication

Set up authentication using one of these methods:

```shell
# Using gcloud CLI
gcloud auth application-default login

# Using environment variable
export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account.json"
```

## Permissions

Ensure your account has Storage Admin permissions:

```shell
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="user:your-email@example.com" \
    --role="roles/storage.admin"
```


Install the required Python packages:


```bash
pip install google-auth google-cloud-storage openai ddgs
```


## Example Script

### Debugging and Bucket Dump

In the example script, a global variable `DEBUG_MODE` controls whether the bucket contents are printed at the end of execution.
Set `DEBUG_MODE = True` in the script to see content of the bucket.

```bash
gcloud init
gcloud auth application-default login
python gcs_json_storage_for_agent.py
```

## Local Testing with Fake GCS

If you want to test the storage functionality locally without using real GCS, you can use [fake-gcs-server](https://github.com/fsouza/fake-gcs-server) :

### Setup Fake GCS with Docker


2. **Install Docker:**

Make sure Docker is installed on your system.

4. **
Create a `docker-compose.yml` File**  in your project root with the following content:


```yaml
version: '3.8'
services:
  fake-gcs-server:
    image: fsouza/fake-gcs-server:latest
    ports:
      - "4443:4443"
    command: ["-scheme", "http", "-port", "4443", "-public-host", "localhost"]
    volumes:
      - ./fake-gcs-data:/data
```

6. **Start the Fake GCS Server:**


```bash
docker-compose up -d
```

This will start the fake GCS server on `http://localhost:4443`.


### Configuring the Script to Use Fake GCS


Set the environment variable so the GCS client directs API calls to the emulator:



```bash
export STORAGE_EMULATOR_HOST="http://localhost:4443"
python gcs_json_for_agent.py
```


When using Fake GCS, authentication isn’t enforced. The client will automatically detect the emulator endpoint.
