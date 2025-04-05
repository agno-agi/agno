# Google Cloud Storage for Agno

This repository provides an example of how to use the `GCSJsonStorage` class as a storage backend for an Agno agent. The storage backend stores session data as JSON blobs in a Google Cloud Storage (GCS) bucket.

> **Note:** The bucket name must be provided explicitly when initializing the storage class. Location and credentials are optional; if not provided, the default credentials (from `GOOGLE_APPLICATION_CREDENTIALS` or the current gcloud CLI project) will be used.

## Prerequisites

- **Google Cloud SDK:**
  Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) and run `gcloud init` to configure your account and project.

- **GCS Permissions:**
  Ensure your account has sufficient permissions (e.g., Storage Admin) to create and manage GCS buckets. You can grant these permissions using:

```bash
  gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
      --member="user:YOUR_EMAIL@example.com" \
      --role="roles/storage.admin"
```


- **Authentication:**
To use default credentials from your gcloud CLI session, run:

```bash
gcloud auth application-default login
```

  - Alternatively, if using a service account, set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to the path of your service account JSON file.

- **Python Dependencies:**

Install the required Python packages:


```bash
pip install google-auth google-cloud-storage openai duckduckgo-search
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
python gcs_json_storage_for_agent.py
```


When using Fake GCS, authentication isn’t enforced. The client will automatically detect the emulator endpoint.
