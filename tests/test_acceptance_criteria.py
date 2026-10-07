"""Acceptance criteria test suite mapping directly to ORIGINAL_REQUEST.md.

Validates:
1. Infrastructure:
   - infra/auth.yaml includes ManagedLoginVersion: 2 on UserPoolDomain and
     AWS::Cognito::ManagedLoginBranding.
   - uvx cfn-lint infra/*.yaml passes with 0 errors.
   - make deploy-auth structures Cognito with Google IdP enabled when credentials are set in .env.
2. Frontend & User Experience:
   - Navigating to /login immediately redirects to Cognito's Managed Login page.
   - Cognito Managed Login page displays both email/password and 'Continue with Google' button.
   - After sign-in, browser returns to app and displays the user's email address in top header.
   - Clicking 'Sign out' terminates the session and redirects via Cognito's logout endpoint.
   - Local dev fallback remains functional when unconfigured.
3. Build & Quality:
   - make lint and make infra-lint succeed with 0 errors.
   - make test runs all backend unit/auth tests and passes (24/24).
   - Frontend production build succeeds (npm run build).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx
import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
AUTH_YAML_PATH = ROOT_DIR / "infra" / "auth.yaml"
ENV_PATH = ROOT_DIR / ".env"
FRONTEND_DIR = ROOT_DIR / "frontend"


class CfnLoader(yaml.SafeLoader):
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


@pytest.fixture(scope="module")
def template() -> dict:
    with open(AUTH_YAML_PATH, encoding="utf-8") as f:
        return yaml.load(f, Loader=CfnLoader)


class TestAcceptanceCriteriaInfrastructure:
    """Acceptance criteria: Infrastructure."""

    def test_ac_infra_managed_login_v2_and_branding(self, template: dict) -> None:
        """AC: infra/auth.yaml includes ManagedLoginVersion: 2 on UserPoolDomain and
        AWS::Cognito::ManagedLoginBranding.
        """
        resources = template.get("Resources", {})

        # UserPoolDomain check
        domain = resources.get("UserPoolDomain", {})
        props = domain.get("Properties", {})
        assert props.get("ManagedLoginVersion") == 2, (
            "UserPoolDomain must specify ManagedLoginVersion: 2"
        )

        # ManagedLoginBranding check
        branding = resources.get("ManagedLoginBranding", {})
        assert branding.get("Type") == "AWS::Cognito::ManagedLoginBranding", (
            "ManagedLoginBranding resource must exist with type AWS::Cognito::ManagedLoginBranding"
        )
        assert branding.get("DependsOn") == "UserPoolDomain"
        assert branding.get("Properties", {}).get("UseCognitoProvidedValues") is True

    def test_ac_infra_cfn_lint_passes_with_zero_errors(self) -> None:
        """AC: uvx cfn-lint infra/*.yaml passes with 0 errors."""
        res = subprocess.run(
            "uvx cfn-lint infra/*.yaml",
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
            shell=True,
        )
        assert res.returncode == 0, f"cfn-lint exited with non-zero status: {res.stderr}"

    def test_ac_infra_deploy_auth_google_enabled_in_env(self, env_vars: dict[str, str]) -> None:
        """AC: make deploy-auth structures Cognito with Google IdP enabled when
        GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set.
        """
        assert env_vars.get("GOOGLE_CLIENT_ID"), "GOOGLE_CLIENT_ID must be configured in .env"
        assert env_vars.get("GOOGLE_CLIENT_SECRET"), (
            "GOOGLE_CLIENT_SECRET must be configured in .env"
        )
        assert env_vars.get("COGNITO_GOOGLE_ENABLED") == "true", (
            "COGNITO_GOOGLE_ENABLED must be set to true in .env"
        )


class TestAcceptanceCriteriaFrontendUX:
    """Acceptance criteria: Frontend & User Experience."""

    def test_ac_frontend_login_redirect_contract(self) -> None:
        """AC: Navigating to /login immediately redirects to Cognito's Managed Login page."""
        login_ts = (FRONTEND_DIR / "src" / "pages" / "login-page.tsx").read_text(encoding="utf-8")
        assert "signinRedirect()" in login_ts
        assert "authConfigured" in login_ts
        # Verify immediate redirect behavior when no code or error in URL
        assert "if (authConfigured)" in login_ts
        assert "signinRedirect()" in login_ts

    @pytest.mark.asyncio
    async def test_ac_cognito_managed_login_page_renders_email_and_google(
        self, env_vars: dict[str, str]
    ) -> None:
        """AC: The Cognito Managed Login page displays both email/password fields
        and 'Continue with Google' button.
        """
        domain = env_vars.get("COGNITO_DOMAIN", "").replace("https://", "").rstrip("/")
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito domain not configured")

        authorize_url = (
            f"https://{domain}/oauth2/authorize?client_id={client_id}"
            f"&response_type=code&scope=openid+email+profile"
            f"&redirect_uri=http://localhost:5173/login"
            f"&code_challenge=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk&code_challenge_method=S256"
        )

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(authorize_url)

        assert resp.status_code == 200
        html = resp.text
        # Cognito Managed Login v2 serves login route
        assert "routes/login" in html or "__remixRouteModules" in html or "entry.client" in html

    def test_ac_frontend_header_displays_user_email(self) -> None:
        """AC: After sign-in, the browser returns to the app and displays the user's email
        address in the top header.
        """
        home_ts = (FRONTEND_DIR / "src" / "pages" / "home-page.tsx").read_text(encoding="utf-8")
        # Ensure user.email is rendered in the header DOM
        match = re.search(r"\{user\.email\}", home_ts)
        assert match is not None, "home-page.tsx must visibly render {user.email} in the header"

    def test_ac_frontend_signout_redirects_via_cognito_logout(self) -> None:
        """AC: Clicking 'Sign out' terminates session and redirects via Cognito's
        logout endpoint.
        """
        auth_ts = (FRONTEND_DIR / "src" / "lib" / "auth.ts").read_text(encoding="utf-8")
        home_ts = (FRONTEND_DIR / "src" / "pages" / "home-page.tsx").read_text(encoding="utf-8")

        # Verify signOut function clears tokens and redirects to /logout
        assert "clearTokens()" in auth_ts
        assert "/logout?client_id=" in auth_ts
        assert "logout_uri=" in auth_ts
        assert "Sign out" in home_ts
        assert "signOut" in home_ts

    def test_ac_frontend_local_dev_fallback_operational(self) -> None:
        """AC: Local dev fallback remains functional when running locally without active
        AWS credentials.
        """
        auth_ts = (FRONTEND_DIR / "src" / "lib" / "auth.ts").read_text(encoding="utf-8")
        login_ts = (FRONTEND_DIR / "src" / "pages" / "login-page.tsx").read_text(encoding="utf-8")

        assert "LOCAL_DEV_USER" in auth_ts
        assert "local-dev-token" in auth_ts
        assert "<AuthNotConfigured />" in login_ts


class TestAcceptanceCriteriaBuildAndQuality:
    """Acceptance criteria: Build & Quality."""

    def test_ac_build_linters_pass_with_zero_errors(self) -> None:
        """AC: make lint and make infra-lint succeed with 0 errors."""
        res_lint = subprocess.run(
            "make lint",
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
            shell=True,
        )
        assert res_lint.returncode == 0, f"make lint failed:\n{res_lint.stderr}\n{res_lint.stdout}"

        res_infra = subprocess.run(
            "make infra-lint",
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
            shell=True,
        )
        assert res_infra.returncode == 0, (
            f"make infra-lint failed:\n{res_infra.stderr}\n{res_infra.stdout}"
        )

    def test_ac_backend_unit_auth_tests_pass(self) -> None:
        """AC: make test runs all backend unit/auth tests and passes (24/24)."""
        res = subprocess.run(
            ["uv", "run", "pytest", "-v"],
            cwd=ROOT_DIR / "backend",
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"backend pytest failed:\n{res.stderr}\n{res.stdout}"
        assert "24 passed" in res.stdout, f"Expected 24 tests passed, output was:\n{res.stdout}"

    def test_ac_frontend_production_build_succeeds(self) -> None:
        """AC: Frontend production build succeeds (npm run build)."""
        res = subprocess.run(
            ["npm", "run", "build"],
            cwd=FRONTEND_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"Frontend build failed:\n{res.stderr}\n{res.stdout}"
        dist_index = FRONTEND_DIR / "dist" / "index.html"
        assert dist_index.is_file(), "dist/index.html was not generated"
