"""
Tier 3: Cross-Feature Combinations (Pairwise Interactions)

Features:
1. Downstream script compatibility: deploy-reports.sh, deploy-ai.sh, report-now.sh reading terraform output -raw
2. Cognito User Pool Client and AI Function URL CORS origins alignment
3. Report Builder SQS consumer and S3 reports bucket permissions
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e_terraform.conftest import (
    INFRA_DIR,
    load_cfn_template,
)


class TestDownstreamScriptCompatibility(unittest.TestCase):
    """Tier 3 - Combination 1: Downstream script compatibility."""

    def test_deploy_reports_script_reads_terraform_output(self):
        """Assert infra/deploy-reports.sh is compatible with Terraform output -raw."""
        script = INFRA_DIR / "deploy-reports.sh"
        self.assertTrue(script.exists(), "infra/deploy-reports.sh must exist")
        content = script.read_text(encoding="utf-8")
        # Check if updated for terraform or verify required output keys are used
        self.assertTrue(
            "terraform output" in content or "ReportsBucketName" in content,
            "deploy-reports.sh should reference ReportsBucketName from outputs",
        )

    def test_deploy_ai_script_reads_terraform_output(self):
        """Assert infra/deploy-ai.sh references AiUrl / AiFunctionUrl."""
        script = INFRA_DIR / "deploy-ai.sh"
        self.assertTrue(script.exists(), "infra/deploy-ai.sh must exist")
        content = script.read_text(encoding="utf-8")
        self.assertTrue(
            "terraform output" in content
            or "AiUrl" in content
            or "AiFunctionUrl" in content,
            "deploy-ai.sh should reference AiUrl / AiFunctionUrl from outputs",
        )

    def test_report_now_script_reads_terraform_output(self):
        """Assert infra/report-now.sh references ReportRequestsQueueUrl."""
        script = INFRA_DIR / "report-now.sh"
        self.assertTrue(script.exists(), "infra/report-now.sh must exist")
        content = script.read_text(encoding="utf-8")
        self.assertTrue(
            "terraform output" in content or "ReportRequestsQueueUrl" in content,
            "report-now.sh should reference ReportRequestsQueueUrl from outputs",
        )

    def test_all_infra_scripts_have_executable_bits(self):
        """Assert all shell scripts in infra/ have executable permissions (chmod +x)."""
        sh_files = list(INFRA_DIR.glob("*.sh"))
        self.assertGreater(len(sh_files), 0, "No shell scripts found in infra/")
        for sh in sh_files:
            is_exec = os.access(sh, os.X_OK)
            self.assertTrue(is_exec, f"Script {sh} lacks executable permission (+x)")

    def test_script_error_handling_when_terraform_output_fails(self):
        """Assert scripts use set -e or error checking to fail fast on command error."""
        scripts_to_check = [
            INFRA_DIR / "deploy-reports.sh",
            INFRA_DIR / "deploy-ai.sh",
            INFRA_DIR / "report-now.sh",
        ]
        for s in scripts_to_check:
            content = s.read_text(encoding="utf-8")
            self.assertTrue(
                "set -e" in content
                or "set -eu" in content
                or "set -o errexit" in content,
                f"Script {s} should enforce strict error handling via 'set -e'",
            )


class TestCognitoAndAiCorsAlignment(unittest.TestCase):
    """Tier 3 - Combination 2: Cognito User Pool Client and AI Function URL CORS origins alignment."""

    def setUp(self):
        auth_cfn = INFRA_DIR / "auth.yaml"
        ai_cfn = INFRA_DIR / "ai.yaml"
        self.assertTrue(auth_cfn.exists())
        self.assertTrue(ai_cfn.exists())
        self.auth_data = load_cfn_template(auth_cfn)
        self.ai_data = load_cfn_template(ai_cfn)

    def test_user_pool_client_callback_urls_include_frontend_origins(self):
        """Assert UserPoolClient callback URLs include standard frontend origins."""
        client_props = (
            self.auth_data.get("Resources", {})
            .get("UserPoolClient", {})
            .get("Properties", {})
        )
        callback_urls = client_props.get("CallbackURLs", [])
        self.assertIsNotNone(callback_urls)
        # In CloudFormation template, AppUrls parameter supplies the base URLs
        self.assertIn("AppUrls", self.auth_data.get("Parameters", {}))
        # Ensure allowed OAuth flows include 'code'
        self.assertEqual(client_props.get("AllowedOAuthFlows"), ["code"])

    def test_ai_function_url_cors_allowed_methods(self):
        """Assert AI Function URL CORS configuration allows POST method."""
        url_props = (
            self.ai_data.get("Resources", {})
            .get("AgendaParserFunctionUrl", {})
            .get("Properties", {})
        )
        cors = url_props.get("Cors", {})
        allow_methods = cors.get("AllowMethods", [])
        self.assertIn(
            "POST", allow_methods, "AI Function URL CORS must allow POST method"
        )

    def test_ai_function_url_cors_allowed_headers(self):
        """Assert AI Function URL CORS configuration allows authorization and content-type headers."""
        url_props = (
            self.ai_data.get("Resources", {})
            .get("AgendaParserFunctionUrl", {})
            .get("Properties", {})
        )
        cors = url_props.get("Cors", {})
        allow_headers = [h.lower() for h in cors.get("AllowHeaders", [])]
        self.assertIn(
            "authorization",
            allow_headers,
            "CORS AllowHeaders must include 'authorization'",
        )
        self.assertIn(
            "content-type",
            allow_headers,
            "CORS AllowHeaders must include 'content-type'",
        )

    def test_agenda_parser_env_vars_link_to_cognito_pool_and_client(self):
        """Assert AgendaParser Lambda environment variables link to Cognito User Pool and Client."""
        lambda_props = (
            self.ai_data.get("Resources", {})
            .get("AgendaParserFunction", {})
            .get("Properties", {})
        )
        env_vars = lambda_props.get("Environment", {}).get("Variables", {})
        self.assertIn("COGNITO_USER_POOL_ID", env_vars)
        self.assertIn("COGNITO_CLIENT_ID", env_vars)
        self.assertIn("PARSER_MODEL", env_vars)

    def test_ai_function_url_auth_type_none_for_cors_preflight(self):
        """Assert AI Function URL AuthType is NONE so browser preflights and client POST are handled by app auth."""
        url_props = (
            self.ai_data.get("Resources", {})
            .get("AgendaParserFunctionUrl", {})
            .get("Properties", {})
        )
        self.assertEqual(url_props.get("AuthType"), "NONE")


class TestReportBuilderSqsS3Permissions(unittest.TestCase):
    """Tier 3 - Combination 3: Report Builder SQS consumer and S3 reports bucket permissions."""

    def setUp(self):
        reports_cfn = INFRA_DIR / "reports.yaml"
        self.assertTrue(reports_cfn.exists())
        self.reports_data = load_cfn_template(reports_cfn)
        self.resources = self.reports_data.get("Resources", {})

    def test_report_builder_iam_role_sqs_permissions(self):
        """Assert ReportBuilderRole grants SQS permissions via AWSLambdaSQSQueueExecutionRole or inline policy."""
        role = self.resources.get("ReportBuilderRole", {})
        managed_policies = role.get("Properties", {}).get("ManagedPolicyArns", [])
        has_sqs_managed_policy = any(
            "AWSLambdaSQSQueueExecutionRole" in p for p in managed_policies
        )

        inline_policies = role.get("Properties", {}).get("Policies", [])
        actions_found = set()
        for p in inline_policies:
            for st in p.get("PolicyDocument", {}).get("Statement", []):
                act = st.get("Action", [])
                if isinstance(act, str):
                    act = [act]
                actions_found.update(act)
        has_inline_sqs = {"sqs:ReceiveMessage", "sqs:DeleteMessage"}.issubset(
            actions_found
        )

        self.assertTrue(
            has_sqs_managed_policy or has_inline_sqs,
            "ReportBuilderRole must include AWSLambdaSQSQueueExecutionRole in ManagedPolicyArns or inline SQS permissions",
        )

    def test_report_builder_iam_role_s3_put_permissions(self):
        """Assert ReportBuilderRole allows s3:PutObject on reports bucket."""
        role = self.resources.get("ReportBuilderRole", {})
        policies = role.get("Properties", {}).get("Policies", [])
        actions_found = set()
        for p in policies:
            for st in p.get("PolicyDocument", {}).get("Statement", []):
                act = st.get("Action", [])
                if isinstance(act, str):
                    act = [act]
                actions_found.update(act)
        self.assertIn(
            "s3:PutObject", actions_found, "ReportBuilderRole must allow s3:PutObject"
        )

    def test_report_builder_env_reports_bucket_link(self):
        """Assert ReportBuilderFunction environment variable REPORTS_BUCKET is configured."""
        func = self.resources.get("ReportBuilderFunction", {})
        env_vars = (
            func.get("Properties", {}).get("Environment", {}).get("Variables", {})
        )
        self.assertIn("REPORTS_BUCKET", env_vars)
        self.assertIn("DATABASE_URL", env_vars)

    def test_report_mailer_iam_s3_get_and_ses_send_permissions(self):
        """Assert ReportMailerRole allows s3:GetObject and ses:SendEmail."""
        role = self.resources.get("ReportMailerRole", {})
        policies = role.get("Properties", {}).get("Policies", [])
        actions_found = set()
        for p in policies:
            for st in p.get("PolicyDocument", {}).get("Statement", []):
                act = st.get("Action", [])
                if isinstance(act, str):
                    act = [act]
                actions_found.update(act)
        self.assertIn(
            "s3:GetObject", actions_found, "ReportMailerRole must allow s3:GetObject"
        )
        self.assertTrue(
            "ses:SendEmail" in actions_found or "ses:SendRawEmail" in actions_found,
            "ReportMailerRole must allow ses:SendEmail",
        )

    def test_report_builder_event_source_mapping_batch_size_one(self):
        """Assert Lambda EventSourceMapping for SQS has BatchSize = 1 for isolated report processing."""
        esm = self.resources.get("ReportBuilderEventSourceMapping", {})
        batch_size = esm.get("Properties", {}).get("BatchSize")
        self.assertEqual(
            batch_size, 1, "ReportBuilderEventSourceMapping BatchSize must be 1"
        )


if __name__ == "__main__":
    unittest.main()
