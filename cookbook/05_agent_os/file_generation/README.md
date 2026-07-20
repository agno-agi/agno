# AgentOS File Generation

Examples for receiving and generating files through AgentOS.

## Examples

- `file_generation_os.py` returns generated files directly in AgentOS responses.
- `s3_file_storage.py` persists uploaded input files and generated output files
  in S3-compatible object storage while storing only media references in the
  database.

## Run the S3 example

Set `AGNO_FILE_OUTPUT_S3_BUCKET`, AWS credentials, and `AWS_REGION`, then run:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/file_generation/s3_file_storage.py
```

Connect AgentOS and test both directions:

- Attach a TXT or CSV file and ask the agent to summarize it.
- Ask the agent to generate a CSV, JSON, PDF, DOCX, TXT, or HTML file.
