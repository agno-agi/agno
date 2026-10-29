"""Deploy or remove an AgentCore Runtime for sandbox sessions. This creates AWS resources.

Builds the ARM64 sandbox image from the Dockerfile, pushes it to an ECR
repository, creates an execution role and a PUBLIC runtime, then prints the
runtime ARN to pass as the sandbox image. --session-storage mounts AgentCore
session storage at /mnt/agno, so an ended session can resume from the copy of
its last checkpoint kept there.

  .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_setup.py deploy --name agno-sandbox
  .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_setup.py teardown --name agno-sandbox

Every resource it creates carries the given name. Set AWS_PROFILE and AWS_REGION
first. The role may call Claude models on Bedrock, so a Claude harness needs no
API key. Code inside the sandbox can use the role too, so anything the role allows,
an agent can do: keep it to the models you run.

Without permission to create ECR repositories or IAM roles, have an
administrator create them, with the role's trust and policy from create_role
below, and pass them in. --skip-build deploys an image already pushed with --tag:

  agentcore_setup.py deploy --name agno-sandbox --repository agno-sandbox \\
      --role-arn arn:aws:iam::123456789012:role/agno-sandbox --tag 1791978197 --skip-build

Teardown with the same --repository or --role-arn leaves those in place.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import boto3

# AgentCore ends a session after this long whatever the sandbox asks for, so
# AgentCoreSandbox(lifetime=...) must not exceed MAX_LIFETIME.
IDLE_TIMEOUT = 900
MAX_LIFETIME = 3600


def find_repository(ecr: Any, name: str, create: bool) -> Dict[str, Any]:
    if create:
        try:
            return ecr.create_repository(repositoryName=name)["repository"]
        except ecr.exceptions.RepositoryAlreadyExistsException:
            pass
    return ecr.describe_repositories(repositoryNames=[name])["repositories"][0]


def build_and_push(ecr: Any, image: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "build_image.py"),
            "--platform",
            "linux/arm64",
            "--tag",
            image,
        ],
        check=True,
    )
    auth = ecr.get_authorization_token()["authorizationData"][0]
    user, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    subprocess.run(
        [
            "docker",
            "login",
            "--username",
            user,
            "--password-stdin",
            auth["proxyEndpoint"],
        ],
        input=password.encode(),
        check=True,
        capture_output=True,
    )
    subprocess.run(["docker", "push", image], check=True)


def create_role(
    iam: Any, name: str, account: str, region: str, repository: Dict[str, Any]
) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:*"
                    },
                },
            }
        ],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": repository["repositoryArn"],
            },
            {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                # Claude models only. Cross-region inference profiles route to the
                # model in other regions, so the foundation model is allowed in each.
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
                    f"arn:aws:bedrock:{region}:{account}:inference-profile/*.anthropic.claude-*",
                ],
            },
        ],
    }
    try:
        role = iam.create_role(
            RoleName=name, AssumeRolePolicyDocument=json.dumps(trust)
        )["Role"]["Arn"]
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=name)["Role"]["Arn"]
    iam.put_role_policy(
        RoleName=name, PolicyName=name, PolicyDocument=json.dumps(policy)
    )
    return role


def deploy_runtime(
    control: Any, name: str, image: str, role: str, session_storage: bool
) -> str:
    runtime_name = name.replace("-", "_")
    config: Dict[str, Any] = dict(
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": image}},
        roleArn=role,
        networkConfiguration={"networkMode": "PUBLIC"},
        # The provider bounds each allocation itself; these are the outer limits.
        lifecycleConfiguration={
            "idleRuntimeSessionTimeout": IDLE_TIMEOUT,
            "maxLifetime": MAX_LIFETIME,
        },
    )
    if session_storage:
        # Each capture keeps a copy of its checkpoint here, and
        # AgentCoreCheckpointTransfer.aresume restores an ended session from it.
        config["filesystemConfigurations"] = [
            {"sessionStorage": {"mountPath": "/mnt/agno"}}
        ]
    existing = [
        r
        for r in control.list_agent_runtimes()["agentRuntimes"]
        if r["agentRuntimeName"] == runtime_name
    ]
    for attempt in range(12):
        try:
            if existing:
                runtime_id = existing[0]["agentRuntimeId"]
                control.update_agent_runtime(agentRuntimeId=runtime_id, **config)
            else:
                runtime_id = control.create_agent_runtime(
                    agentRuntimeName=runtime_name, **config
                )["agentRuntimeId"]
            break
        except control.exceptions.ValidationException as error:
            # A new role takes a few seconds to become assumable.
            if "Role validation failed" not in str(error) or attempt == 11:
                raise
            time.sleep(5)
    while True:
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        if runtime["status"] not in ("CREATING", "UPDATING"):
            break
        time.sleep(5)
    if runtime["status"] != "READY":
        raise SystemExit(
            f"Runtime is {runtime['status']}: {runtime.get('failureReason')}"
        )
    return runtime["agentRuntimeArn"]


def deploy(
    session: boto3.session.Session,
    name: str,
    tag: str,
    repository_name: Optional[str],
    role_arn: Optional[str],
    skip_build: bool,
    session_storage: bool,
) -> None:
    region = session.region_name
    account = session.client("sts").get_caller_identity()["Account"]
    ecr, iam = session.client("ecr"), session.client("iam")
    control = session.client("bedrock-agentcore-control")

    repository = find_repository(
        ecr, repository_name or name, create=repository_name is None
    )
    image = repository["repositoryUri"] + ":" + tag
    if not skip_build:
        build_and_push(ecr, image)
    role = role_arn or create_role(iam, name, account, region, repository)
    print("Runtime ARN:", deploy_runtime(control, name, image, role, session_storage))
    print(
        f"Runtime maxLifetime: {MAX_LIFETIME} s, idle timeout: {IDLE_TIMEOUT} s."
        f" Keep AgentCoreSandbox(lifetime=...) at or below {MAX_LIFETIME}."
    )


def teardown(
    session: boto3.session.Session, name: str, keep_repository: bool, keep_role: bool
) -> None:
    control, iam, ecr = (
        session.client(s) for s in ("bedrock-agentcore-control", "iam", "ecr")
    )
    for runtime in control.list_agent_runtimes()["agentRuntimes"]:
        if runtime["agentRuntimeName"] == name.replace("-", "_"):
            control.delete_agent_runtime(agentRuntimeId=runtime["agentRuntimeId"])
            print("Deleted runtime", runtime["agentRuntimeArn"])
    if not keep_role:
        try:
            iam.delete_role_policy(RoleName=name, PolicyName=name)
            iam.delete_role(RoleName=name)
            print("Deleted role", name)
        except iam.exceptions.NoSuchEntityException:
            pass
    if not keep_repository:
        try:
            ecr.delete_repository(repositoryName=name, force=True)
            print("Deleted repository", name)
        except ecr.exceptions.RepositoryNotFoundException:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=("deploy", "teardown"))
    parser.add_argument("--name", default="agno-sandbox")
    parser.add_argument(
        "--tag",
        help="Image tag, by default the current time. A new tag makes AgentCore pull a new version",
    )
    parser.add_argument(
        "--repository", help="An existing ECR repository to push to and deploy from"
    )
    parser.add_argument(
        "--role-arn", help="An existing execution role, so no IAM role is created"
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Deploy the image already pushed with --tag",
    )
    parser.add_argument(
        "--session-storage",
        action="store_true",
        help="Mount session storage at /mnt/agno so ended sessions can resume from it",
    )
    args = parser.parse_args()
    if args.skip_build and not args.tag:
        parser.error("--skip-build needs the --tag of an image already pushed")
    session = boto3.session.Session(region_name=os.environ.get("AWS_REGION"))
    if args.action == "deploy":
        deploy(
            session,
            args.name,
            args.tag or str(int(time.time())),
            args.repository,
            args.role_arn,
            args.skip_build,
            args.session_storage,
        )
    else:
        teardown(session, args.name, bool(args.repository), bool(args.role_arn))


if __name__ == "__main__":
    main()
