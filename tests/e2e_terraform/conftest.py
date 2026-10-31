"""
Shared fixtures, configuration, and authoritative specifications for the E2E Terraform test suite.
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path
from typing import Any

import boto3
import yaml

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INFRA_DIR = PROJECT_ROOT / "infra"
BOOTSTRAP_DIR = INFRA_DIR / "bootstrap"
DOCS_DIR = PROJECT_ROOT / "docs"
MAKEFILE_PATH = PROJECT_ROOT / "Makefile"
README_PATH = PROJECT_ROOT / "README.md"
ENV_PATH = PROJECT_ROOT / ".env"


class CfnLoader(yaml.SafeLoader):
    """YAML loader that handles CloudFormation shorthand intrinsic tags (!Ref, !Sub, etc.)."""


def _cfn_tag_ctor(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> dict:
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node)}
    if isinstance(node, yaml.MappingNode):
        return {tag_suffix: loader.construct_mapping(node)}
    return {tag_suffix: None}


CfnLoader.add_multi_constructor("!", _cfn_tag_ctor)


def load_cfn_template(path: Path) -> dict:
    """Safely load CloudFormation YAML template handling shorthand tags."""
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=CfnLoader)


# Authoritative Contract Specification (from ORIGINAL_REQUEST.md & PROJECT.md)
EXPECTED_16_OUTPUTS: set[str] = {
    "UserPoolId",
    "UserPoolClientId",
    "Domain",
    "Issuer",
    "GoogleEnabled",
    "Region",
    "ReportsBucketName",
    "ReportRequestsQueueUrl",
    "ReportRequestsQueueArn",
    "ReportRequestsDLQUrl",
    "ReportBuilderFunctionName",
    "ReportMailerFunctionName",
    "AiFunctionUrl",
    "AiUrl",
    "AgendaParserFunctionName",
    "AgendaParserLogGroup",
}

# Authoritative Live Physical Resources (from AWS Survey & .env)
LIVE_PHYSICAL_IDS = {
    "account_id": "277206319329",
    "region": "us-east-1",
    "project_name": "new-project",
    "cognito_user_pool_id": "us-east-1_9U6SeBfDJ",
    "cognito_client_id": "4toue9ji24bieqcdc9ibnns5gq",
    "cognito_domain_prefix": "new-project-277206319329",
    "s3_reports_bucket": "new-project-reports-277206319329",
    "sqs_queue_url": "https://sqs.us-east-1.amazonaws.com/277206319329/new-project-report-requests",
    "sqs_dlq_url": "https://sqs.us-east-1.amazonaws.com/277206319329/new-project-report-requests-dlq",
    "scheduler_name": "new-project-weekly-report",
    "report_builder_func": "new-project-report-builder",
    "report_mailer_func": "new-project-report-mailer",
    "agenda_parser_func": "new-project-agenda-parser",
    "ai_function_url_id": "tbslumdps7wcdldinbmw6sjwjm0fhjtq",
    "ai_function_url": "https://tbslumdps7wcdldinbmw6sjwjm0fhjtq.lambda-url.us-east-1.on.aws/",
}

LIVE_COGNITO_USER_COUNT = 8
LIVE_S3_HISTORICAL_REPORTS = [
    "reports/2026-W38.csv",
    "reports/2026-W39.csv",
    "reports/2026-W40.csv",
    "reports/2026-W41.csv",
]

# Authoritative HCP Organization & OIDC contracts
EXPECTED_HCP_ORG = "ooad-MaksIMMum"
EXPECTED_OIDC_URL = "https://app.terraform.io"
EXPECTED_OIDC_AUDIENCE = "aws.workload.identity"
EXPECTED_ROLE_NAME = "hcp-terraform-ooad-MaksIMMum"


def load_env_variables() -> None:
    """Ensure .env variables are loaded into os.environ if present."""
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key not in os.environ or not os.environ[key]:
                        os.environ[key] = val


load_env_variables()


def get_cmd_env() -> dict[str, str]:
    """Return environment dictionary with ~/.local/bin in PATH."""
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
    return env


def run_command(
    cmd: list[str] | str, cwd: Path = PROJECT_ROOT
) -> subprocess.CompletedProcess:
    """Execute command with enhanced PATH and return CompletedProcess."""
    shell = isinstance(cmd, str)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=get_cmd_env(),
        shell=shell,
        capture_output=True,
        check=False,
        text=True,
    )


def require_artifact(
    path: Path | list[Path], milestone_id: str, description: str
) -> None:
    """
    Progressive testability gate:
    If artifact is missing:
    - If E2E_STRICT=1: raises AssertionError (failing the test).
    - Otherwise: raises unittest.SkipTest with milestone dependency info.
    """
    paths = [path] if isinstance(path, Path) else path
    missing = [p for p in paths if not p.exists()]
    if missing:
        msg = (
            f"Missing required artifact(s) {missing} for {milestone_id}: {description}"
        )
        if os.environ.get("E2E_STRICT", "0") == "1":
            raise AssertionError(msg)
        raise unittest.SkipTest(f"[{milestone_id} Pending] {msg}")


def require_feature(condition: bool, milestone_id: str, description: str) -> None:
    """
    Progressive testability gate for features within existing files:
    If condition is False:
    - If E2E_STRICT=1: raises AssertionError (failing the test).
    - Otherwise: raises unittest.SkipTest with milestone dependency info.
    """
    if not condition:
        msg = f"Feature '{description}' not yet implemented for {milestone_id}"
        if os.environ.get("E2E_STRICT", "0") == "1":
            raise AssertionError(msg)
        raise unittest.SkipTest(f"[{milestone_id} Pending] {msg}")


def parse_hcl_blocks(file_path: Path, block_type: str) -> list[dict[str, Any]]:
    """Simple parser extracting top-level block definitions from HCL files."""
    if not file_path.exists():
        return []
    content = file_path.read_text(encoding="utf-8")
    # Matches: block_type "label1" ("label2")? {
    pattern = rf'{block_type}\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{{'
    matches = []
    for m in re.finditer(pattern, content):
        matches.append(
            {
                "type": block_type,
                "label1": m.group(1),
                "label2": m.group(2) if m.group(2) else None,
                "span": m.span(),
            }
        )
    return matches


def get_boto3_client(service_name: str, region_name: str = "us-east-1"):
    """Instantiate boto3 client with active credentials."""
    return boto3.client(
        service_name,
        region_name=region_name,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
    )
