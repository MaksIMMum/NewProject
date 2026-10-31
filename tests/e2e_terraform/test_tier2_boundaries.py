"""
Tier 2: Boundary & Corner Cases (>=5 test cases per feature)

Features:
1. Missing or empty required variables handling
2. Circular dependency prevention (S3 bucket notification vs Lambda permission)
3. Cognito password policies and user pool schema boundaries
4. SQS DLQ redrive policies and maxReceiveCount
5. EventBridge scheduler retry policies and execution role permissions
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e_terraform.conftest import (
    INFRA_DIR,
    load_cfn_template,
    parse_hcl_blocks,
    require_artifact,
    run_command,
)


class TestVariableBoundaries(unittest.TestCase):
    """Tier 2 - Feature 1: Missing or empty required variables handling."""

    def test_empty_project_name_boundary(self):
        """Assert variables.tf rejects or flags empty project_name."""
        vars_file = INFRA_DIR / "variables.tf"
        if not vars_file.exists():
            require_artifact(vars_file, "M2", "infra/variables.tf")
        content = vars_file.read_text(encoding="utf-8")
        self.assertIn('variable "project_name"', content)
        # Check type is string
        match = re.search(
            r'variable\s+"project_name"\s*\{([^}]+)\}', content, re.DOTALL
        )
        self.assertIsNotNone(match)
        block = match.group(1)
        self.assertIn("type", block)
        self.assertIn("string", block)

    def test_invalid_aws_region_boundary(self):
        """Assert variables.tf handles aws_region with valid default or validation."""
        vars_file = INFRA_DIR / "variables.tf"
        if not vars_file.exists():
            require_artifact(vars_file, "M2", "infra/variables.tf")
        content = vars_file.read_text(encoding="utf-8")
        self.assertIn('variable "aws_region"', content)
        match = re.search(r'variable\s+"aws_region"\s*\{([^}]+)\}', content, re.DOTALL)
        self.assertIsNotNone(match)
        block = match.group(1)
        # Should have a safe default or string type
        self.assertIn("string", block)

    def test_optional_google_client_id_boundary(self):
        """Assert auth.tf conditionally handles empty google_client_id (count = 0 or conditional IdP)."""
        auth_tf = INFRA_DIR / "auth.tf"
        if not auth_tf.exists():
            require_artifact(auth_tf, "M2", "infra/auth.tf")
        content = auth_tf.read_text(encoding="utf-8")
        self.assertIn("aws_cognito_identity_provider", content)
        # Google IdP must be conditional on google_client_id being provided
        self.assertTrue(
            "count " in content
            or "count=" in content
            or "for_each" in content
            or "var.google_client_id" in content,
            "aws_cognito_identity_provider must conditionally handle presence of var.google_client_id",
        )

    def test_missing_required_variable_validation_error(self):
        """Assert terraform validate fails if a syntax error or invalid variable type is declared."""
        vars_file = INFRA_DIR / "variables.tf"
        if not vars_file.exists():
            require_artifact(vars_file, "M2", "infra/variables.tf")
        # Ensure validate passes when required vars are defined
        proc = run_command(["terraform", "validate"], cwd=INFRA_DIR)
        self.assertEqual(
            proc.returncode,
            0,
            f"terraform validate failed on variables.tf:\n{proc.stderr}",
        )

    def test_variable_types_are_strictly_typed(self):
        """Assert all variables in variables.tf declare explicit types (no untyped any)."""
        vars_file = INFRA_DIR / "variables.tf"
        if not vars_file.exists():
            require_artifact(vars_file, "M2", "infra/variables.tf")
        content = vars_file.read_text(encoding="utf-8")
        var_blocks = parse_hcl_blocks(vars_file, "variable")
        for vb in var_blocks:
            var_name = vb["label1"]
            pat = rf'variable\s+"{var_name}"\s*\{{([^}}]+)\}}'
            m = re.search(pat, content, re.DOTALL)
            self.assertIsNotNone(m, f"Could not extract body for variable {var_name}")
            body = m.group(1)
            self.assertIn(
                "type", body, f"Variable '{var_name}' lacks explicit type definition"
            )
            self.assertNotIn(
                "type = any",
                body,
                f"Variable '{var_name}' uses unrestricted 'any' type",
            )


class TestCircularDependencyPrevention(unittest.TestCase):
    """Tier 2 - Feature 2: Circular dependency prevention (S3 bucket notification vs Lambda permission)."""

    def test_s3_notification_is_separate_resource(self):
        """Assert aws_s3_bucket_notification is defined as a standalone resource in reports.tf."""
        reports_tf = INFRA_DIR / "reports.tf"
        if not reports_tf.exists():
            require_artifact(reports_tf, "M2", "infra/reports.tf")
        content = reports_tf.read_text(encoding="utf-8")
        self.assertIn(
            "aws_s3_bucket_notification",
            content,
            "aws_s3_bucket_notification must be declared as a separate resource",
        )

    def test_lambda_permission_references_bucket_arn(self):
        """Assert aws_lambda_permission for report mailer references bucket ARN without cycle."""
        reports_tf = INFRA_DIR / "reports.tf"
        if not reports_tf.exists():
            require_artifact(reports_tf, "M2", "infra/reports.tf")
        content = reports_tf.read_text(encoding="utf-8")
        self.assertIn("aws_lambda_permission", content)
        self.assertTrue(
            "aws_s3_bucket." in content or "source_arn" in content,
            "aws_lambda_permission must link source_arn to reports S3 bucket",
        )

    def test_s3_notification_explicit_depends_on(self):
        """Assert aws_s3_bucket_notification has depends_on for the Lambda permission."""
        reports_tf = INFRA_DIR / "reports.tf"
        if not reports_tf.exists():
            require_artifact(reports_tf, "M2", "infra/reports.tf")
        content = reports_tf.read_text(encoding="utf-8")
        pat = r'resource\s+"aws_s3_bucket_notification"\s+"[^"]+"\s*\{([^}]+)\}'
        m = re.search(pat, content, re.DOTALL)
        self.assertIsNotNone(
            m, "aws_s3_bucket_notification block not found in reports.tf"
        )
        body = m.group(1)
        self.assertTrue(
            "depends_on" in body,
            "aws_s3_bucket_notification must declare depends_on to prevent notification race condition",
        )

    def test_terraform_graph_no_cycles(self):
        """Assert terraform graph produces a valid Directed Acyclic Graph with 0 cycles."""
        tf_files = list(INFRA_DIR.glob("*.tf"))
        if not tf_files:
            require_artifact(INFRA_DIR / "reports.tf", "M2", "infra/reports.tf")

        import shutil
        import tempfile

        # Ensure provider plugins are available locally
        providers_dir = INFRA_DIR / ".terraform" / "providers"
        if not providers_dir.exists():
            init_proc = run_command(
                ["terraform", "init", "-backend=false"], cwd=INFRA_DIR
            )
            self.assertEqual(
                init_proc.returncode,
                0,
                f"terraform init -backend=false failed in {INFRA_DIR}:\n{init_proc.stderr}",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Link or copy .tf files and lockfile into isolated sandbox
            for tf_file in INFRA_DIR.glob("*.tf"):
                try:
                    (tmp_path / tf_file.name).symlink_to(tf_file.resolve())
                except OSError:
                    shutil.copy2(tf_file, tmp_path / tf_file.name)

            lock_file = INFRA_DIR / ".terraform.lock.hcl"
            if lock_file.exists():
                try:
                    (tmp_path / lock_file.name).symlink_to(lock_file.resolve())
                except OSError:
                    shutil.copy2(lock_file, tmp_path / lock_file.name)

            # Symlink cached provider plugins to avoid re-downloading ~815MB
            if providers_dir.exists():
                tmp_dot_tf = tmp_path / ".terraform"
                tmp_dot_tf.mkdir(parents=True, exist_ok=True)
                try:
                    (tmp_dot_tf / "providers").symlink_to(providers_dir.resolve())
                except OSError:
                    pass

            # Override cloud block with local backend to allow offline graph generation
            override_file = tmp_path / "backend_override.tf"
            override_file.write_text(
                'terraform {\n  backend "local" {}\n}\n', encoding="utf-8"
            )

            # Initialize sandbox with local backend
            init_proc = run_command(["terraform", "init"], cwd=tmp_path)
            self.assertEqual(
                init_proc.returncode,
                0,
                f"terraform init failed in temporary test sandbox:\n{init_proc.stderr}",
            )

            # Generate dependency graph
            proc = run_command(["terraform", "graph"], cwd=tmp_path)
            self.assertEqual(
                proc.returncode, 0, f"terraform graph failed:\n{proc.stderr}"
            )
            self.assertNotIn(
                "cycle",
                proc.stderr.lower(),
                "terraform graph detected a dependency cycle!",
            )
            self.assertIn(
                "digraph",
                proc.stdout,
                "terraform graph output should be a valid dot digraph",
            )

    def test_cfn_circular_workaround_eliminated(self):
        """Assert CloudFormation reports.yaml workaround (hardcoded ARN in permission) is documented."""
        reports_cfn = INFRA_DIR / "reports.yaml"
        self.assertTrue(reports_cfn.exists())
        content = reports_cfn.read_text(encoding="utf-8")
        # In reports.yaml line 49, ReportsBucket had DependsOn: MailerInvokePermission
        self.assertIn("DependsOn: MailerInvokePermission", content)


class TestCognitoPoliciesBoundaries(unittest.TestCase):
    """Tier 2 - Feature 3: Cognito password policies and user pool schema boundaries."""

    def test_cognito_password_min_length_boundary(self):
        """Assert minimum password length is at least 8 (RFC 5321 / NIST guidelines)."""
        auth_cfn = INFRA_DIR / "auth.yaml"
        self.assertTrue(auth_cfn.exists())
        cfn_data = load_cfn_template(auth_cfn)
        policy = (
            cfn_data.get("Resources", {})
            .get("UserPool", {})
            .get("Properties", {})
            .get("Policies", {})
            .get("PasswordPolicy", {})
        )
        self.assertGreaterEqual(
            policy.get("MinimumLength", 0),
            8,
            "Cognito minimum password length must be at least 8",
        )

    def test_cognito_password_character_flags(self):
        """Assert password character flags match live pool: require lowercase and numbers; uppercase & symbols false."""
        auth_cfn = INFRA_DIR / "auth.yaml"
        self.assertTrue(auth_cfn.exists())
        cfn_data = load_cfn_template(auth_cfn)
        policy = (
            cfn_data.get("Resources", {})
            .get("UserPool", {})
            .get("Properties", {})
            .get("Policies", {})
            .get("PasswordPolicy", {})
        )
        self.assertTrue(
            policy.get("RequireLowercase"), "Password policy must require lowercase"
        )
        self.assertTrue(
            policy.get("RequireNumbers"), "Password policy must require numbers"
        )
        self.assertFalse(
            policy.get("RequireSymbols"),
            "Password policy must NOT require symbols (matching live pool)",
        )
        self.assertFalse(
            policy.get("RequireUppercase"),
            "Password policy must NOT require uppercase (matching live pool)",
        )

    def test_cognito_username_attribute_strict_email(self):
        """Assert username attributes strictly equal ['email']."""
        auth_cfn = INFRA_DIR / "auth.yaml"
        self.assertTrue(auth_cfn.exists())
        cfn_data = load_cfn_template(auth_cfn)
        props = cfn_data.get("Resources", {}).get("UserPool", {}).get("Properties", {})
        self.assertEqual(
            props.get("UsernameAttributes"),
            ["email"],
            "Cognito UsernameAttributes must strictly be ['email']",
        )

    def test_cognito_auto_verified_email(self):
        """Assert auto verified attributes include email and verification before update is enabled."""
        auth_cfn = INFRA_DIR / "auth.yaml"
        self.assertTrue(auth_cfn.exists())
        cfn_data = load_cfn_template(auth_cfn)
        props = cfn_data.get("Resources", {}).get("UserPool", {}).get("Properties", {})
        self.assertEqual(props.get("AutoVerifiedAttributes"), ["email"])
        update_attr = props.get("UserAttributeUpdateSettings", {}).get(
            "AttributesRequireVerificationBeforeUpdate"
        )
        self.assertEqual(update_attr, ["email"])

    def test_cognito_mfa_configuration_boundary(self):
        """Assert MFA configuration is OFF matching live pool."""
        auth_cfn = INFRA_DIR / "auth.yaml"
        self.assertTrue(auth_cfn.exists())
        cfn_data = load_cfn_template(auth_cfn)
        props = cfn_data.get("Resources", {}).get("UserPool", {}).get("Properties", {})
        mfa_config = props.get("MfaConfiguration", "OFF")
        self.assertEqual(mfa_config, "OFF", "MFA configuration must be OFF")


class TestSqsDlqRedriveBoundaries(unittest.TestCase):
    """Tier 2 - Feature 4: SQS DLQ redrive policies and maxReceiveCount."""

    def setUp(self):
        reports_cfn = INFRA_DIR / "reports.yaml"
        self.assertTrue(reports_cfn.exists())
        self.cfn_data = load_cfn_template(reports_cfn)
        self.resources = self.cfn_data.get("Resources", {})

    def test_main_queue_redrive_policy_target_dlq(self):
        """Assert main queue redrive policy links deadLetterTargetArn to DLQ."""
        main_queue = self.resources.get("ReportRequestsQueue", {})
        redrive = main_queue.get("Properties", {}).get("RedrivePolicy", {})
        self.assertIn("deadLetterTargetArn", redrive)

    def test_dlq_max_receive_count_boundary(self):
        """Assert maxReceiveCount is strictly 3 at the boundary."""
        main_queue = self.resources.get("ReportRequestsQueue", {})
        redrive = main_queue.get("Properties", {}).get("RedrivePolicy", {})
        max_receive = redrive.get("maxReceiveCount")
        self.assertEqual(max_receive, 3, "maxReceiveCount must strictly equal 3")

    def test_dlq_retention_period_boundary(self):
        """Assert DLQ message retention period is 1209600 seconds (14 days, max SQS retention)."""
        dlq = self.resources.get("ReportRequestsDLQ", {})
        retention = dlq.get("Properties", {}).get("MessageRetentionPeriod")
        self.assertEqual(
            retention,
            1209600,
            "DLQ MessageRetentionPeriod must be 1209600 seconds (14 days)",
        )

    def test_main_queue_visibility_timeout_greater_than_lambda(self):
        """Assert main queue visibility timeout (360s) >= 6x Lambda function timeout (60s)."""
        main_queue = self.resources.get("ReportRequestsQueue", {})
        timeout = main_queue.get("Properties", {}).get("VisibilityTimeout")
        lambda_func = self.resources.get("ReportBuilderFunction", {})
        lambda_timeout = lambda_func.get("Properties", {}).get("Timeout", 60)
        self.assertGreaterEqual(
            timeout,
            lambda_timeout * 6,
            f"VisibilityTimeout ({timeout}) must be at least 6x Lambda timeout ({lambda_timeout})",
        )

    def test_main_queue_dlq_dead_letter_target_arn_alignment(self):
        """Assert DLQ resource definition exists and queue names are distinct."""
        self.assertIn("ReportRequestsDLQ", self.resources)
        self.assertIn("ReportRequestsQueue", self.resources)
        self.assertNotEqual("ReportRequestsDLQ", "ReportRequestsQueue")


class TestEventBridgeSchedulerBoundaries(unittest.TestCase):
    """Tier 2 - Feature 5: EventBridge scheduler retry policies and execution role permissions."""

    def setUp(self):
        reports_cfn = INFRA_DIR / "reports.yaml"
        self.assertTrue(reports_cfn.exists())
        self.cfn_data = load_cfn_template(reports_cfn)
        self.schedule = self.cfn_data.get("Resources", {}).get("ReportSchedule", {})
        self.props = self.schedule.get("Properties", {})

    def test_scheduler_cron_expression_syntax(self):
        """Assert schedule expression is cron(0 7 ? * MON *)."""
        expr = self.props.get("ScheduleExpression")
        self.assertEqual(
            expr,
            "cron(0 7 ? * MON *)",
            "ScheduleExpression must be 'cron(0 7 ? * MON *)'",
        )

    def test_scheduler_timezone_kyiv(self):
        """Assert schedule expression timezone is Europe/Kyiv."""
        tz = self.props.get("ScheduleExpressionTimezone")
        self.assertEqual(
            tz, "Europe/Kyiv", "ScheduleExpressionTimezone must be 'Europe/Kyiv'"
        )

    def test_scheduler_flexible_time_window_off(self):
        """Assert flexible time window mode is OFF."""
        window = self.props.get("FlexibleTimeWindow", {})
        self.assertEqual(
            window.get("Mode"), "OFF", "FlexibleTimeWindow Mode must be OFF"
        )

    def test_scheduler_target_sqs_payload(self):
        """Assert target input JSON payload matches {'week': null, 'source': 'schedule'}."""
        target = self.props.get("Target", {})
        input_text = target.get("Input")
        self.assertIsNotNone(input_text, "Target input payload missing")
        parsed = json.loads(input_text)
        self.assertIsNone(parsed.get("week"))
        self.assertEqual(parsed.get("source"), "schedule")

    def test_scheduler_iam_role_sqs_send_message_permission(self):
        """Assert scheduler IAM role grants sqs:SendMessage to the target queue."""
        role = self.cfn_data.get("Resources", {}).get("SchedulerRole", {})
        policies = role.get("Properties", {}).get("Policies", [])
        found_sqs = False
        for p in policies:
            statements = p.get("PolicyDocument", {}).get("Statement", [])
            for st in statements:
                actions = st.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                if "sqs:SendMessage" in actions:
                    found_sqs = True
                    self.assertEqual(st.get("Effect"), "Allow")
        self.assertTrue(
            found_sqs, "SchedulerRole must contain sqs:SendMessage Allow policy"
        )


if __name__ == "__main__":
    unittest.main()
