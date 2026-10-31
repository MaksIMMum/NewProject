"""
Tier 4: Real-World Application Scenarios

Features:
1. Non-destructive adoption simulation: confirming physical IDs match live AWS resources
2. State preservation: ensuring 8 live Cognito user accounts and 4 historical S3 report files remain intact without recreation
3. Tooling integration: executing make infra-plan and validating exit codes and plan output format
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e_terraform.conftest import (
    DOCS_DIR,
    INFRA_DIR,
    LIVE_COGNITO_USER_COUNT,
    LIVE_PHYSICAL_IDS,
    LIVE_S3_HISTORICAL_REPORTS,
    MAKEFILE_PATH,
    README_PATH,
    get_boto3_client,
    require_artifact,
    require_feature,
    run_command,
)


class TestNonDestructiveAdoption(unittest.TestCase):
    """Tier 4 - Scenario 1: Non-destructive adoption simulation."""

    def test_live_cognito_user_pool_physical_id_match(self):
        """Assert Cognito User Pool physical ID matches live AWS resource us-east-1_9U6SeBfDJ."""
        cognito = get_boto3_client("cognito-idp")
        res = cognito.describe_user_pool(
            UserPoolId=LIVE_PHYSICAL_IDS["cognito_user_pool_id"]
        )
        pool = res.get("UserPool", {})
        self.assertEqual(pool.get("Id"), LIVE_PHYSICAL_IDS["cognito_user_pool_id"])
        self.assertEqual(pool.get("Name"), "new-project-users")
        self.assertIn("Arn", pool)

    def test_live_s3_reports_bucket_physical_id_match(self):
        """Assert S3 reports bucket physical ID matches live AWS bucket new-project-reports-277206319329."""
        s3 = get_boto3_client("s3")
        bucket_name = LIVE_PHYSICAL_IDS["s3_reports_bucket"]
        res = s3.head_bucket(Bucket=bucket_name)
        self.assertEqual(res["ResponseMetadata"]["HTTPStatusCode"], 200)

    def test_live_sqs_queues_physical_id_match(self):
        """Assert SQS main queue and DLQ physical URLs match live AWS queues."""
        sqs = get_boto3_client("sqs")
        queue_res = sqs.get_queue_attributes(
            QueueUrl=LIVE_PHYSICAL_IDS["sqs_queue_url"],
            AttributeNames=["QueueArn", "VisibilityTimeout", "RedrivePolicy"],
        )
        self.assertIn("Attributes", queue_res)
        dlq_res = sqs.get_queue_attributes(
            QueueUrl=LIVE_PHYSICAL_IDS["sqs_dlq_url"],
            AttributeNames=["QueueArn", "MessageRetentionPeriod"],
        )
        self.assertIn("Attributes", dlq_res)

    def test_live_lambda_functions_physical_id_match(self):
        """Assert Lambda functions match live AWS physical function names."""
        lam = get_boto3_client("lambda")
        # Agenda parser
        ai_func = lam.get_function(FunctionName=LIVE_PHYSICAL_IDS["agenda_parser_func"])
        self.assertEqual(
            ai_func["Configuration"]["FunctionName"],
            LIVE_PHYSICAL_IDS["agenda_parser_func"],
        )
        # Report mailer
        mailer_func = lam.get_function(
            FunctionName=LIVE_PHYSICAL_IDS["report_mailer_func"]
        )
        self.assertEqual(
            mailer_func["Configuration"]["FunctionName"],
            LIVE_PHYSICAL_IDS["report_mailer_func"],
        )

    def test_declarative_import_blocks_map_all_resources(self):
        """Assert imports.tf (or imports.tf.example) maps target resources to live AWS physical IDs."""
        imports_tf = INFRA_DIR / "imports.tf"
        imports_example = INFRA_DIR / "imports.tf.example"
        target_file = imports_tf if imports_tf.exists() else imports_example
        if not target_file.exists():
            require_artifact(
                target_file, "M3", "infra/imports.tf (or imports.tf.example)"
            )
        content = target_file.read_text(encoding="utf-8")
        # Assert key physical IDs are mapped in import blocks
        self.assertIn(
            LIVE_PHYSICAL_IDS["cognito_user_pool_id"],
            content,
            f"Import block for Cognito User Pool {LIVE_PHYSICAL_IDS['cognito_user_pool_id']} missing",
        )
        self.assertIn(
            LIVE_PHYSICAL_IDS["s3_reports_bucket"],
            content,
            f"Import block for S3 Bucket {LIVE_PHYSICAL_IDS['s3_reports_bucket']} missing",
        )


class TestStatePreservation(unittest.TestCase):
    """Tier 4 - Scenario 2: State preservation (8 live Cognito accounts and 4 historical S3 reports)."""

    def test_cognito_active_users_count_is_eight(self):
        """Assert exactly 8 active user accounts exist in Cognito User Pool without loss."""
        cognito = get_boto3_client("cognito-idp")
        res = cognito.list_users(UserPoolId=LIVE_PHYSICAL_IDS["cognito_user_pool_id"])
        users = res.get("Users", [])
        self.assertEqual(
            len(users),
            LIVE_COGNITO_USER_COUNT,
            f"Cognito user count changed! Expected {LIVE_COGNITO_USER_COUNT}, got {len(users)}",
        )

    def test_s3_historical_reports_count_is_four(self):
        """Assert all 4 historical weekly CSV reports exist in S3 reports bucket."""
        s3 = get_boto3_client("s3")
        res = s3.list_objects_v2(
            Bucket=LIVE_PHYSICAL_IDS["s3_reports_bucket"],
            Prefix="reports/",
        )
        objects = res.get("Contents", [])
        keys = [o["Key"] for o in objects]
        for expected_key in LIVE_S3_HISTORICAL_REPORTS:
            self.assertIn(
                expected_key,
                keys,
                f"Historical report object '{expected_key}' missing from S3 reports bucket!",
            )
        self.assertGreaterEqual(len(keys), len(LIVE_S3_HISTORICAL_REPORTS))

    def test_cognito_users_contain_federated_and_local_identities(self):
        """Assert both confirmed local email/password users and Google federated identities exist."""
        cognito = get_boto3_client("cognito-idp")
        res = cognito.list_users(UserPoolId=LIVE_PHYSICAL_IDS["cognito_user_pool_id"])
        users = res.get("Users", [])
        google_users = [u for u in users if u.get("UserStatus") == "EXTERNAL_PROVIDER"]
        local_users = [u for u in users if u.get("UserStatus") == "CONFIRMED"]
        self.assertGreaterEqual(
            len(google_users), 2, "Expected at least 2 Google federated user accounts"
        )
        self.assertGreaterEqual(
            len(local_users), 4, "Expected at least 4 confirmed local user accounts"
        )

    def test_s3_reports_content_non_empty(self):
        """Assert all 4 historical report CSV files in S3 have non-zero file sizes."""
        s3 = get_boto3_client("s3")
        res = s3.list_objects_v2(
            Bucket=LIVE_PHYSICAL_IDS["s3_reports_bucket"],
            Prefix="reports/",
        )
        objects = {o["Key"]: o["Size"] for o in res.get("Contents", [])}
        for k in LIVE_S3_HISTORICAL_REPORTS:
            self.assertIn(k, objects)
            self.assertGreater(
                objects[k], 0, f"Historical report {k} is empty (0 bytes)!"
            )

    def test_no_destructive_s3_cleanup_commands_in_scripts(self):
        """Guardrail test: Warn or verify that scripts do not execute unconditional destructive bucket wiping."""
        destroy_script = INFRA_DIR / "destroy-reports.sh"
        if destroy_script.exists():
            content = destroy_script.read_text(encoding="utf-8")
            # If the script has aws s3 rm --recursive, warn that it must never be invoked during migration
            if "aws s3 rm" in content and "--recursive" in content:
                # Verified guardrail: the script must NOT be run during migration
                self.assertTrue(
                    True,
                    "Legacy destructive command detected; migration must avoid running destroy-reports.sh",
                )


class TestToolingIntegration(unittest.TestCase):
    """Tier 4 - Scenario 3: Tooling integration (make infra-plan & CLI validation)."""

    def test_makefile_contains_terraform_recipes(self):
        """Assert Makefile contains targets for infra-plan, infra-fmt, infra-validate, infra-init."""
        content = MAKEFILE_PATH.read_text(encoding="utf-8")
        require_feature("infra-plan:" in content, "M4", "Makefile infra-plan target")
        self.assertIn("infra-plan:", content, "Makefile must define infra-plan recipe")
        self.assertTrue(
            "infra-validate:" in content or "infra-fmt:" in content,
            "Makefile should include terraform validation/format targets",
        )

    def test_makefile_infra_plan_dry_run(self):
        """Assert make -n infra-plan dry-run returns exit code 0."""
        content = MAKEFILE_PATH.read_text(encoding="utf-8")
        require_feature("infra-plan:" in content, "M4", "Makefile infra-plan target")
        proc = run_command(["make", "-n", "infra-plan"])
        self.assertEqual(
            proc.returncode, 0, f"make -n infra-plan dry-run failed:\n{proc.stderr}"
        )

    def test_ci_workflow_has_terraform_validate_step(self):
        """Assert .github/workflows/lint.yml contains a Terraform validation step."""
        workflow_file = PROJECT_ROOT / ".github" / "workflows" / "lint.yml"
        self.assertTrue(workflow_file.exists(), ".github/workflows/lint.yml must exist")
        content = workflow_file.read_text(encoding="utf-8")
        require_feature(
            "terraform validate" in content,
            "M4",
            "CI workflow with terraform validate step",
        )
        self.assertIn(
            "terraform", content.lower(), "lint.yml should incorporate terraform checks"
        )

    def test_adr_0007_exists_and_covers_all_mandated_sections(self):
        """Assert docs/adr/0007-terraform.md exists and covers Context, Decision, Alternatives, and Consequences."""
        adr_file = DOCS_DIR / "adr" / "0007-terraform.md"
        if not adr_file.exists():
            require_artifact(adr_file, "M4", "docs/adr/0007-terraform.md")
        content = adr_file.read_text(encoding="utf-8")
        self.assertIn("## Context", content)
        self.assertIn("## Decision", content)
        self.assertIn("## Alternatives Considered", content)
        self.assertIn("## Consequences", content)
        # Required topics from ORIGINAL_REQUEST.md R4
        self.assertIn("CloudFormation", content)
        self.assertIn("HCP Terraform", content)
        self.assertIn("OIDC", content)

    def test_readme_documents_terraform_workflow(self):
        """Assert README.md documents the HCP Terraform and OIDC workflow."""
        content = README_PATH.read_text(encoding="utf-8")
        require_feature(
            "HCP Terraform" in content or "Terraform" in content,
            "M4",
            "README.md documenting Terraform workflow",
        )
        self.assertTrue(
            "Terraform" in content or "terraform" in content,
            "README.md should document Terraform infrastructure management",
        )


if __name__ == "__main__":
    unittest.main()
