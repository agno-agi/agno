"""A sandboxed Claude agent whose checkpoints live in an S3 bucket instead of a local directory.

A deployment with more than one replica has no shared disk to put checkpoints on, so the
queue worker refuses the local default. S3CheckpointStore keeps each checkpoint as one
content-addressed object that every replica can read.

Create a bucket, give this process AWS credentials the way any boto3 client takes them
(AWS_PROFILE, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or an instance role), build the
runtime image, run Postgres, and export ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN:

    export AWS_PROFILE=... AWS_DEFAULT_REGION=us-east-1
    aws s3 mb s3://my-agno-checkpoints
    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
    ./cookbook/scripts/run_pgvector.sh
    .venv/bin/python cookbook/frameworks/sandbox/docker/sandbox_s3_checkpoints.py

Install agno[s3] for boto3. An S3-compatible service such as MinIO works too: point boto3 at
it with the standard AWS_ENDPOINT_URL_S3 variable, or pass endpoint_url= to the store.
"""

import os
import subprocess
from uuid import uuid4

import boto3

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.s3 import S3CheckpointStore

# Your bucket. The prefix keeps checkpoints apart from anything else stored in it.
bucket = "my-agno-checkpoints"
checkpoints = S3CheckpointStore(bucket, prefix="sandbox/checkpoints")

agent = ClaudeAgent(
    id="coder",
    model="claude-sonnet-4-6",
    permission_mode="bypassPermissions",
    db=PostgresDb(
        db_url=os.getenv(
            "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
        )
    ),
    sandbox=DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=1024,
        checkpoints=checkpoints,
    ),
)

session_id = "sandbox-s3-" + uuid4().hex[:8]

first = agent.run(
    "Write hello.py that prints hello, run it, and reply with just its output.",
    session_id=session_id,
)
print("Turn 1:", first.status.value, "-", first.content)

# The turn's checkpoint is now an object in the bucket, named by the digest of its bytes.
s3 = boto3.client("s3")
listing = s3.list_objects_v2(Bucket=bucket, Prefix=checkpoints.prefix)
for item in listing.get("Contents", []):
    print("Checkpoint object:", item["Key"], item["Size"], "bytes")

# Lose the host: remove the session's container, which the coordinator had kept warm for the
# next turn. On a real deployment this is a crashed machine or the next turn landing on
# another replica. The only copy of the session's files is now the object in the bucket.
containers = subprocess.run(
    ["docker", "ps", "-aq", "--filter", "label=io.agno.sandbox.session=" + session_id],
    capture_output=True,
    text=True,
    check=True,
).stdout.split()
subprocess.run(["docker", "rm", "-f", *containers], capture_output=True, check=True)
print("Removed the session's container:", ", ".join(containers))

# The next turn starts a new container and restores the checkpoint from S3 into it.
second = agent.run(
    "What file did you create in this session? Reply with the file name only.",
    session_id=session_id,
)
print("Turn 2:", second.status.value, "-", second.content)
print("Resumed a warm computer:", second.metadata["sandbox"]["resumed"])
assert second.metadata["sandbox"]["resumed"] is False, (
    "the turn ran on a computer restored from the bucket"
)
assert "hello.py" in (second.content or "")
