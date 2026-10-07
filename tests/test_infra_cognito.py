"""Automated test suite for Cognito Managed Login v2 and Google IdP infrastructure.

Validates:
- CloudFormation template schema and resource specifications in infra/auth.yaml
- ManagedLoginVersion: 2 configuration on UserPoolDomain
- ManagedLoginBranding resource with UseCognitoProvidedValues: true and DependsOn
- UserPoolTier: ESSENTIALS and self sign-up settings on UserPool
- GoogleIdentityProvider condition, scopes, and attribute mapping
- UserPoolClient OAuth flows, scopes, identity providers, and URLs
- cfn-lint static analysis execution
- Live AWS Cognito resources when credentials are configured
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
AUTH_YAML_PATH = ROOT_DIR / "infra" / "auth.yaml"
ENV_PATH = ROOT_DIR / ".env"


class CfnLoader(yaml.SafeLoader):
    """YAML loader that handles CloudFormation shorthand intrinsic tags."""

    pass


def _cfn_tag_ctor(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> dict:
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node)}
    if isinstance(node, yaml.MappingNode):
        return {tag_suffix: loader.construct_mapping(node)}
    return {tag_suffix: None}


CfnLoader.add_multi_constructor("!", _cfn_tag_ctor)


@pytest.fixture(scope="module")
def template() -> dict:
    assert AUTH_YAML_PATH.is_file(), f"Template not found at {AUTH_YAML_PATH}"
    with open(AUTH_YAML_PATH, encoding="utf-8") as f:
        return yaml.load(f, Loader=CfnLoader)


@pytest.fixture(scope="module")
def env_vars() -> dict[str, str]:
    vars_dict: dict[str, str] = {}
    if ENV_PATH.is_file():
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vars_dict[k.strip()] = v.strip()
    return vars_dict


class TestCloudFormationAuthTemplate:
    """Static inspection of infra/auth.yaml against Managed Login v2 specifications."""

    def test_template_loads_successfully(self, template: dict) -> None:
        assert "Resources" in template, "CloudFormation template must define 'Resources'"
        assert "Parameters" in template, "CloudFormation template must define 'Parameters'"
        assert "Outputs" in template, "CloudFormation template must define 'Outputs'"

    def test_user_pool_tier_essentials(self, template: dict) -> None:
        user_pool = template["Resources"].get("UserPool")
        assert user_pool is not None, "Resource 'UserPool' must exist"
        props = user_pool.get("Properties", {})
        assert props.get("UserPoolTier") == "ESSENTIALS", (
            "Cognito Managed Login v2 requires UserPoolTier to be set to ESSENTIALS"
        )

    def test_user_pool_self_signup_enabled(self, template: dict) -> None:
        user_pool = template["Resources"]["UserPool"]
        props = user_pool.get("Properties", {})
        admin_create = props.get("AdminCreateUserConfig", {})
        assert admin_create.get("AllowAdminCreateUserOnly") is False, (
            "Self sign-up must be allowed (AllowAdminCreateUserOnly: false)"
        )

    def test_user_pool_email_verification(self, template: dict) -> None:
        user_pool = template["Resources"]["UserPool"]
        props = user_pool.get("Properties", {})
        assert props.get("UsernameAttributes") == ["email"], (
            "UsernameAttributes must be configured for email"
        )
        assert props.get("AutoVerifiedAttributes") == ["email"], (
            "AutoVerifiedAttributes must include email"
        )

    def test_user_pool_domain_managed_login_v2(self, template: dict) -> None:
        domain = template["Resources"].get("UserPoolDomain")
        assert domain is not None, "Resource 'UserPoolDomain' must exist"
        props = domain.get("Properties", {})
        assert props.get("ManagedLoginVersion") == 2, (
            "UserPoolDomain must have ManagedLoginVersion: 2 for Hosted UI v2"
        )
        assert "Domain" in props, "UserPoolDomain must define a Domain property"
        assert props.get("UserPoolId") == {"Ref": "UserPool"}

    def test_managed_login_branding_resource(self, template: dict) -> None:
        branding = template["Resources"].get("ManagedLoginBranding")
        assert branding is not None, "Resource 'ManagedLoginBranding' must exist in template"
        assert branding.get("Type") == "AWS::Cognito::ManagedLoginBranding", (
            "ManagedLoginBranding must be of type AWS::Cognito::ManagedLoginBranding"
        )
        assert branding.get("DependsOn") == "UserPoolDomain", (
            "ManagedLoginBranding must depend on UserPoolDomain"
        )
        props = branding.get("Properties", {})
        assert props.get("UseCognitoProvidedValues") is True, (
            "ManagedLoginBranding must set UseCognitoProvidedValues: true"
        )
        assert props.get("UserPoolId") == {"Ref": "UserPool"}
        assert props.get("ClientId") == {"Ref": "UserPoolClient"}

    def test_google_identity_provider_specification(self, template: dict) -> None:
        google_idp = template["Resources"].get("GoogleIdentityProvider")
        assert google_idp is not None, "Resource 'GoogleIdentityProvider' must exist"
        assert google_idp.get("Type") == "AWS::Cognito::UserPoolIdentityProvider"
        assert google_idp.get("Condition") == "HasGoogle", (
            "GoogleIdentityProvider must be guarded by Condition: HasGoogle"
        )
        props = google_idp.get("Properties", {})
        assert props.get("ProviderName") == "Google"
        assert props.get("ProviderType") == "Google"
        details = props.get("ProviderDetails", {})
        assert details.get("client_id") == {"Ref": "GoogleClientId"}
        assert details.get("client_secret") == {"Ref": "GoogleClientSecret"}
        assert details.get("authorize_scopes") == "openid email profile"

        mapping = props.get("AttributeMapping", {})
        assert mapping.get("email") == "email"
        assert mapping.get("email_verified") == "email_verified"
        assert mapping.get("name") == "name"

    def test_google_parameters_security(self, template: dict) -> None:
        params = template["Parameters"]
        assert "GoogleClientId" in params
        assert "GoogleClientSecret" in params
        assert params["GoogleClientSecret"].get("NoEcho") is True, (
            "GoogleClientSecret parameter must be marked NoEcho: true for security"
        )

    def test_user_pool_client_oauth_settings(self, template: dict) -> None:
        client = template["Resources"].get("UserPoolClient")
        assert client is not None, "Resource 'UserPoolClient' must exist"
        props = client.get("Properties", {})
        assert props.get("AllowedOAuthFlows") == ["code"], (
            "AllowedOAuthFlows must be ['code'] for Authorization Code grant"
        )
        assert props.get("AllowedOAuthScopes") == ["openid", "email", "profile"], (
            "AllowedOAuthScopes must include openid, email, and profile"
        )
        assert props.get("AllowedOAuthFlowsUserPoolClient") is True
        assert props.get("GenerateSecret") is False, (
            "Public SPA client must not generate a client secret"
        )

        providers = props.get("SupportedIdentityProviders")
        assert providers == {
            "If": ["HasGoogle", ["COGNITO", {"Ref": "GoogleIdentityProvider"}], ["COGNITO"]]
        }, "SupportedIdentityProviders must conditionally include Google and COGNITO"

    def test_user_pool_client_redirect_urls(self, template: dict) -> None:
        client = template["Resources"]["UserPoolClient"]
        props = client.get("Properties", {})
        assert "CallbackURLs" in props, "CallbackURLs must be defined"
        assert "LogoutURLs" in props, "LogoutURLs must be defined"

    def test_outputs_defined(self, template: dict) -> None:
        outputs = template["Outputs"]
        required_outputs = [
            "UserPoolId",
            "UserPoolClientId",
            "Domain",
            "Issuer",
            "Region",
            "GoogleEnabled",
        ]
        for key in required_outputs:
            assert key in outputs, f"Output '{key}' must be defined in template"

    def test_cfn_lint_passes(self) -> None:
        result = subprocess.run(
            "uvx cfn-lint infra/*.yaml",
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
            shell=True,
        )
        assert result.returncode == 0, (
            f"cfn-lint failed with return code {result.returncode}:\n"
            f"{result.stderr}\n{result.stdout}"
        )


class TestCognitoLiveDeployment:
    """Verifies the live deployed CloudFormation stack and Cognito resources in AWS."""

    @pytest.fixture(autouse=True)
    def check_aws_cli(self, env_vars: dict[str, str]) -> None:
        aws_path = shutil.which("aws") or os.path.expanduser("~/.local/bin/aws")
        if not (Path(aws_path).is_file() and os.access(aws_path, os.X_OK)):
            pytest.skip("AWS CLI is not installed in environment")
        if not env_vars.get("AWS_ACCESS_KEY_ID") or not env_vars.get("AWS_SECRET_ACCESS_KEY"):
            pytest.skip("AWS credentials are not configured in .env")

    def _run_aws(
        self, args: list[str], env_vars: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        aws_bin = shutil.which("aws") or os.path.expanduser("~/.local/bin/aws")
        env = os.environ.copy()
        env["AWS_ACCESS_KEY_ID"] = env_vars.get("AWS_ACCESS_KEY_ID", "")
        env["AWS_SECRET_ACCESS_KEY"] = env_vars.get("AWS_SECRET_ACCESS_KEY", "")
        env["AWS_DEFAULT_REGION"] = env_vars.get("AWS_REGION", "us-east-1")
        env["PATH"] = f"{os.path.expanduser('~/.local/bin')}:{env.get('PATH', '')}"
        return subprocess.run(
            [aws_bin, *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_live_cloudformation_stack_status(self, env_vars: dict[str, str]) -> None:
        stack_name = f"{env_vars.get('PROJECT_NAME', 'new-project')}-auth"
        res = self._run_aws(
            [
                "cloudformation",
                "describe-stacks",
                "--stack-name",
                stack_name,
                "--query",
                "Stacks[0].StackStatus",
                "--output",
                "text",
            ],
            env_vars,
        )
        assert res.returncode == 0, f"Failed to describe stack {stack_name}: {res.stderr}"
        status = res.stdout.strip()
        assert status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"), (
            f"Stack status is '{status}', expected CREATE_COMPLETE or UPDATE_COMPLETE"
        )

    def test_live_stack_resources(self, env_vars: dict[str, str]) -> None:
        stack_name = f"{env_vars.get('PROJECT_NAME', 'new-project')}-auth"
        res = self._run_aws(
            [
                "cloudformation",
                "describe-stack-resources",
                "--stack-name",
                stack_name,
                "--output",
                "json",
            ],
            env_vars,
        )
        assert res.returncode == 0, f"Failed to list stack resources: {res.stderr}"
        data = json.loads(res.stdout)
        types = {r["ResourceType"]: r["ResourceStatus"] for r in data.get("StackResources", [])}

        assert "AWS::Cognito::UserPool" in types
        assert "AWS::Cognito::UserPoolDomain" in types
        assert "AWS::Cognito::UserPoolClient" in types
        assert "AWS::Cognito::ManagedLoginBranding" in types, (
            "ManagedLoginBranding must be deployed in live stack"
        )
        assert types["AWS::Cognito::ManagedLoginBranding"] in (
            "CREATE_COMPLETE",
            "UPDATE_COMPLETE",
        )
        if env_vars.get("GOOGLE_CLIENT_ID"):
            assert "AWS::Cognito::UserPoolIdentityProvider" in types
            assert types["AWS::Cognito::UserPoolIdentityProvider"] in (
                "CREATE_COMPLETE",
                "UPDATE_COMPLETE",
            )

    def test_live_user_pool_domain_managed_login_v2(self, env_vars: dict[str, str]) -> None:
        full_domain = env_vars.get("COGNITO_DOMAIN", "")
        domain_prefix = full_domain.split(".auth.")[0]
        res = self._run_aws(
            [
                "cognito-idp",
                "describe-user-pool-domain",
                "--domain",
                domain_prefix,
                "--output",
                "json",
            ],
            env_vars,
        )
        assert res.returncode == 0, f"Failed to describe user pool domain: {res.stderr}"
        data = json.loads(res.stdout)
        desc = data.get("DomainDescription", {})
        ver = desc.get("ManagedLoginVersion")
        assert ver == 2, f"Live Cognito domain has ManagedLoginVersion={ver}, expected 2"
        assert desc.get("Status") == "ACTIVE", (
            f"Live Cognito domain status is {desc.get('Status')}, expected ACTIVE"
        )

    def test_live_user_pool_client_oauth_and_providers(self, env_vars: dict[str, str]) -> None:
        pool_id = env_vars.get("COGNITO_USER_POOL_ID", "")
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        res = self._run_aws(
            [
                "cognito-idp",
                "describe-user-pool-client",
                "--user-pool-id",
                pool_id,
                "--client-id",
                client_id,
                "--output",
                "json",
            ],
            env_vars,
        )
        assert res.returncode == 0, f"Failed to describe user pool client: {res.stderr}"
        data = json.loads(res.stdout)
        client = data.get("UserPoolClient", {})
        assert client.get("AllowedOAuthFlows") == ["code"]
        assert set(client.get("AllowedOAuthScopes", [])) == {"openid", "email", "profile"}
        providers = client.get("SupportedIdentityProviders", [])
        assert "COGNITO" in providers
        if env_vars.get("GOOGLE_CLIENT_ID"):
            assert "Google" in providers, "Google must be in SupportedIdentityProviders"

        callbacks = client.get("CallbackURLs", [])
        logout_urls = client.get("LogoutURLs", [])
        assert any("/login" in url for url in callbacks), "CallbackURLs must contain /login URL"
        assert any("/login" in url for url in logout_urls), "LogoutURLs must contain /login URL"
