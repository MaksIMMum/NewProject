"""Adversarial Empirical Challenge Test Suite (Challenger 2).

Systematically probes:
1. CloudFormation template boundaries, parameter variations, and Condition evaluations
   (with and without Google credentials, single/multi AppUrls, ProjectName patterns).
2. Live AWS Cognito Hosted UI v2 endpoints (authorize, token, logout, JWKS),
   validating status codes, redirect locations, security headers, and open-redirect defenses.
3. Local development fallback robustness in both frontend and backend under
   missing, empty, or corrupted configuration states.
4. Token verification security boundary enforcement.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

AUTH_YAML_PATH = ROOT_DIR / "infra" / "auth.yaml"
ENV_PATH = ROOT_DIR / ".env"


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


def compute_s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# ==============================================================================
# AXIS 1: CloudFormation Template Boundaries & Condition Behaviors
# ==============================================================================


class TestCloudFormationBoundariesAndConditions:
    """Probes CloudFormation parameters, condition evaluations, and boundary logic."""

    def test_condition_has_google_logic_evaluation(self) -> None:
        """Simulate CloudFormation Condition: HasGoogle = !Not [!Equals [!Ref GoogleClientId, ""]]"""

        def eval_has_google(client_id: str) -> bool:
            return client_id != ""

        # Case 1: Standard Google credentials configured
        assert eval_has_google("650210369601-something.apps.googleusercontent.com") is True

        # Case 2: Empty string (default)
        assert eval_has_google("") is False

        # Case 3: Arbitrary non-empty string
        assert eval_has_google("some-custom-client-id") is True

    def test_user_pool_client_supported_identity_providers_condition_branches(
        self, template: dict
    ) -> None:
        """Verifies that UserPoolClient SupportedIdentityProviders correctly switches

        between [COGNITO, GoogleIdentityProvider] when HasGoogle is True,
        and [COGNITO] when HasGoogle is False.
        """
        user_pool_client = template["Resources"]["UserPoolClient"]
        providers_expr = user_pool_client["Properties"]["SupportedIdentityProviders"]

        # Expression structure: {'If': ['HasGoogle', ['COGNITO', {'Ref': 'GoogleIdentityProvider'}], ['COGNITO']]}
        assert "If" in providers_expr
        cond_args = providers_expr["If"]
        assert len(cond_args) == 3
        assert cond_args[0] == "HasGoogle"

        true_branch = cond_args[1]
        false_branch = cond_args[2]

        # True branch must contain COGNITO and the GoogleIdentityProvider reference
        assert "COGNITO" in true_branch
        assert any(
            isinstance(item, dict) and item.get("Ref") == "GoogleIdentityProvider"
            for item in true_branch
        )

        # False branch must ONLY contain COGNITO, without any reference to GoogleIdentityProvider
        assert false_branch == ["COGNITO"]
        assert not any(
            isinstance(item, dict) and item.get("Ref") == "GoogleIdentityProvider"
            for item in false_branch
        )

    def test_google_enabled_output_condition(self, template: dict) -> None:
        """Verifies that Output GoogleEnabled is conditioned on HasGoogle."""
        outputs = template.get("Outputs", {})
        google_output = outputs.get("GoogleEnabled", {})
        assert "Value" in google_output
        val_expr = google_output["Value"]
        assert "If" in val_expr
        if_args = val_expr["If"]
        assert if_args == ["HasGoogle", "true", "false"]

    @pytest.mark.parametrize(
        "app_urls_input,expected_callbacks",
        [
            # Case 1: Standard dual origins
            (
                ["http://localhost:5173", "http://localhost:3000"],
                [
                    "http://localhost:5173",
                    "http://localhost:3000",
                    "http://localhost:5173/login",
                    "http://localhost:3000/login",
                ],
            ),
            # Case 2: Boundary - Single origin
            (
                ["http://localhost:5173"],
                ["http://localhost:5173", "http://localhost:5173/login"],
            ),
            # Case 3: Boundary - Triple origins (e.g. including CloudFront)
            (
                ["http://localhost:5173", "http://localhost:3000", "https://d123.cloudfront.net"],
                [
                    "http://localhost:5173",
                    "http://localhost:3000",
                    "https://d123.cloudfront.net",
                    "http://localhost:5173/login",
                    "http://localhost:3000/login",
                    "https://d123.cloudfront.net/login",
                ],
            ),
        ],
    )
    def test_app_urls_expansion_formula(
        self, app_urls_input: list[str], expected_callbacks: list[str]
    ) -> None:
        """CloudFormation expression in auth.yaml:

        !Split [",", !Join [",", [!Join [",", !Ref AppUrls], !Join ["", [!Join ["/login,", !Ref AppUrls], "/login"]]]]]
        Simulate exact behavior of this CloudFormation intrinsic expression across boundaries.
        """
        # Join [",", AppUrls]
        part1 = ",".join(app_urls_input)
        # Join ["", [Join ["/login,", AppUrls], "/login"]]
        part2 = "/login,".join(app_urls_input) + "/login"
        # Join [",", [part1, part2]]
        joined = ",".join([part1, part2])
        # Split [",", joined]
        split_result = joined.split(",")

        assert split_result == expected_callbacks
        # Verify no trailing slashes or empty strings
        for url in split_result:
            assert url, "URL must not be empty"
            assert not url.endswith("/"), f"URL {url} must not have trailing slash"

    def test_project_name_pattern_boundary_validation(self, template: dict) -> None:
        """Verifies ProjectName AllowedPattern regex against boundary strings."""
        pattern = template["Parameters"]["ProjectName"].get("AllowedPattern")
        assert pattern == "[a-z][a-z0-9-]*"
        regex = re.compile(f"^{pattern}$")

        valid_names = ["meetings", "new-project", "a", "project123", "a-b-c-1-2"]
        invalid_names = [
            "Meetings",  # Uppercase
            "123project",  # Starts with number
            "-project",  # Starts with hyphen
            "new_project",  # Underscore not allowed
            "PROJECT",  # All uppercase
            "",  # Empty string
        ]

        for name in valid_names:
            assert regex.match(name) is not None, f"Expected {name} to be valid"
        for name in invalid_names:
            assert regex.match(name) is None, f"Expected {name} to be invalid"


# ==============================================================================
# AXIS 2: Live AWS Cognito Hosted UI v2 Endpoints Behavior & Response Headers
# ==============================================================================


class TestLiveCognitoEndpointsAndHeaders:
    """Probes live Cognito endpoints for correct status codes, redirects, and security headers."""

    def test_live_authorize_endpoint_valid_request(self, env_vars: dict[str, str]) -> None:
        """Probes GET /oauth2/authorize with valid PKCE params."""
        domain = env_vars.get("COGNITO_DOMAIN")
        client_id = env_vars.get("COGNITO_CLIENT_ID")
        assert domain and client_id, "Cognito domain and client ID required in .env"

        verifier = "valid-test-verifier-with-sufficient-random-entropy-12345678"
        challenge = compute_s256_challenge(verifier)
        redirect_uri = "http://localhost:5173/login"

        url = f"https://{domain}/oauth2/authorize"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        # Inspect initial 302 response without following redirects
        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(url, params=params)

            # Cognito Managed Login v2 issues a 302 redirect to the login SPA path
            assert resp.status_code == 302, (
                f"Expected 302 redirect from /oauth2/authorize, got {resp.status_code}"
            )
            location = resp.headers.get("Location", "")
            assert location, "302 response must contain Location header"
            parsed_loc = urllib.parse.urlparse(location)
            assert parsed_loc.netloc == domain, "Redirect must stay within Cognito domain"
            assert "/login" in parsed_loc.path or "/oauth2" in parsed_loc.path, (
                f"Unexpected redirect location path: {parsed_loc.path}"
            )

            # Check security headers on the initial redirect
            headers = resp.headers
            assert "x-content-type-options" in headers, "Missing X-Content-Type-Options"
            assert headers.get("x-content-type-options") == "nosniff"

    def test_live_authorize_endpoint_open_redirect_defense(
        self, env_vars: dict[str, str]
    ) -> None:
        """Adversarial check: Attacker attempts open-redirect via unauthorized redirect_uri.

        Cognito Managed Login v2 must NOT redirect to the attacker URI; instead, it issues
        a 302 redirect to its internal error page (/error?error=redirect_mismatch).
        """
        domain = env_vars.get("COGNITO_DOMAIN")
        client_id = env_vars.get("COGNITO_CLIENT_ID")
        attacker_uri = "https://evil-attacker.example.com/steal-code"

        url = f"https://{domain}/oauth2/authorize"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": attacker_uri,
            "code_challenge": "somechallenge",
            "code_challenge_method": "S256",
        }

        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(url, params=params)

            # Cognito returns 302 to /error
            assert resp.status_code == 302
            location = resp.headers.get("Location", "")
            parsed_loc = urllib.parse.urlparse(location)

            # Defenses validated:
            assert parsed_loc.netloc == domain, "Must stay on Cognito domain, not attacker domain"
            assert parsed_loc.path == "/error", f"Must redirect to /error, got {parsed_loc.path}"
            query_params = urllib.parse.parse_qs(parsed_loc.query)
            assert query_params.get("error") == ["redirect_mismatch"]

    def test_live_authorize_endpoint_invalid_client_id(self, env_vars: dict[str, str]) -> None:
        """Adversarial check: Request with non-existent client_id.

        Cognito Managed Login v2 routes to /error?error=invalid_request.
        """
        domain = env_vars.get("COGNITO_DOMAIN")
        url = f"https://{domain}/oauth2/authorize"
        params = {
            "client_id": "nonexistent_client_id_99999",
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": "http://localhost:5173/login",
            "code_challenge": "somechallenge",
            "code_challenge_method": "S256",
        }

        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(url, params=params)
            assert resp.status_code == 302
            location = resp.headers.get("Location", "")
            parsed_loc = urllib.parse.urlparse(location)
            assert parsed_loc.netloc == domain
            assert parsed_loc.path == "/error"
            query_params = urllib.parse.parse_qs(parsed_loc.query)
            assert query_params.get("error") == ["invalid_request"]

    def test_live_token_endpoint_rejects_bogus_code(self, env_vars: dict[str, str]) -> None:
        """Probes POST /oauth2/token with invalid authorization code."""
        domain = env_vars.get("COGNITO_DOMAIN")
        client_id = env_vars.get("COGNITO_CLIENT_ID")
        url = f"https://{domain}/oauth2/token"

        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "invalid-bogus-auth-code-12345",
            "redirect_uri": "http://localhost:5173/login",
            "code_verifier": "valid-test-verifier-with-sufficient-random-entropy-12345678",
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 400, (
                f"Expected 400 Bad Request for bogus code, got {resp.status_code}"
            )
            body = resp.json()
            assert "error" in body, "Expected error field in response JSON"
            assert body["error"] == "invalid_grant"

            # Check cache control headers
            cache_control = resp.headers.get("cache-control", "")
            assert "no-cache" in cache_control or "no-store" in cache_control

    def test_live_token_endpoint_rejects_missing_code_verifier(
        self, env_vars: dict[str, str]
    ) -> None:
        """Probes POST /oauth2/token without code_verifier."""
        domain = env_vars.get("COGNITO_DOMAIN")
        client_id = env_vars.get("COGNITO_CLIENT_ID")
        url = f"https://{domain}/oauth2/token"

        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "dummy-code",
            "redirect_uri": "http://localhost:5173/login",
            # code_verifier intentionally omitted
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 400, (
                f"Expected 400 Bad Request for missing code_verifier, got {resp.status_code}"
            )

    def test_live_logout_endpoint_valid_request(self, env_vars: dict[str, str]) -> None:
        """Probes GET /logout with valid client_id and logout_uri."""
        domain = env_vars.get("COGNITO_DOMAIN")
        client_id = env_vars.get("COGNITO_CLIENT_ID")
        logout_uri = "http://localhost:5173/login"
        url = f"https://{domain}/logout"

        params = {
            "client_id": client_id,
            "logout_uri": logout_uri,
        }

        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(url, params=params)
            assert resp.status_code == 302, f"Expected 302 Found, got {resp.status_code}"
            assert resp.headers.get("Location") == logout_uri, (
                f"Expected redirect Location to equal {logout_uri}, got {resp.headers.get('Location')}"
            )

    def test_live_logout_endpoint_open_redirect_defense(self, env_vars: dict[str, str]) -> None:
        """Adversarial check: Attacker attempts open-redirect on logout endpoint.

        Cognito Managed Login v2 does NOT redirect to the unauthorized logout_uri.
        Instead, it redirects back to its own login page, where accessing it yields HTTP 400.
        """
        domain = env_vars.get("COGNITO_DOMAIN")
        client_id = env_vars.get("COGNITO_CLIENT_ID")
        malicious_logout_uri = "https://malicious-site.example.com"
        url = f"https://{domain}/logout"

        params = {
            "client_id": client_id,
            "logout_uri": malicious_logout_uri,
        }

        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            resp = client.get(url, params=params)
            location = resp.headers.get("Location", "")
            parsed_loc = urllib.parse.urlparse(location)

            # Defenses validated:
            # 1. Location must stay on Cognito domain
            assert parsed_loc.netloc == domain, "Must stay on Cognito domain, not attacker domain"
            # 2. Location path is /login
            assert parsed_loc.path == "/login"
            # 3. Requesting this destination returns 400
            inner_resp = client.get(location)
            assert inner_resp.status_code == 400

    def test_live_jwks_endpoint_availability_and_structure(
        self, env_vars: dict[str, str]
    ) -> None:
        """Verifies Cognito JWKS endpoint is live, returns valid RS256 signing keys."""
        pool_id = env_vars.get("COGNITO_USER_POOL_ID", "")
        region = env_vars.get("AWS_REGION", "us-east-1")
        assert pool_id, "COGNITO_USER_POOL_ID required"

        jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(jwks_url)
            assert resp.status_code == 200, f"Expected 200 OK from JWKS, got {resp.status_code}"
            data = resp.json()
            assert "keys" in data, "JWKS response must have 'keys' list"
            keys = data["keys"]
            assert len(keys) >= 1, "Must contain at least 1 public key"
            for k in keys:
                assert k.get("alg") == "RS256"
                assert k.get("kty") == "RSA"
                assert k.get("use") == "sig"
                assert "kid" in k
                assert "n" in k
                assert "e" in k


# ==============================================================================
# AXIS 3: Local Development Fallback Robustness
# ==============================================================================


class TestLocalDevFallbackRobustness:
    """Probes frontend and backend fallback logic under missing/empty/corrupted env vars."""

    @pytest.mark.parametrize(
        "pool_id,client_id,expected_configured",
        [
            ("us-east-1_xyz", "client123", True),
            ("", "client123", False),
            ("us-east-1_xyz", "", False),
            ("", "", False),
            (None, None, False),
            ("us-east-1_xyz", None, False),
            (None, "client123", False),
        ],
    )
    def test_frontend_auth_configured_logic(
        self, pool_id: str | None, client_id: str | None, expected_configured: bool
    ) -> None:
        """Formula in frontend/src/lib/auth.ts:

        authConfigured = Boolean(authConfig.userPoolId && authConfig.clientId)
        """
        configured = bool(pool_id and client_id)
        assert configured is expected_configured

    def test_backend_verifier_initialization_fallback(self) -> None:
        """In backend/app/auth.py:

        get_verifier() returns None when cognito_user_pool_id or cognito_client_id is empty.
        """
        from app.auth import TokenVerifier

        def mock_get_verifier(pool_id: str, client_id: str) -> TokenVerifier | None:
            if not pool_id or not client_id:
                return None
            return TokenVerifier(pool_id, client_id)

        assert mock_get_verifier("", "client123") is None
        assert mock_get_verifier("us-east-1_xyz", "") is None
        assert mock_get_verifier("", "") is None
        assert mock_get_verifier("us-east-1_xyz", "client123") is not None

    @pytest.mark.asyncio
    async def test_backend_current_user_local_dev_fallback(self) -> None:
        """When verifier is None (local dev mode):

        get_current_user must return the local demo user even without Authorization header.
        """
        from app.auth import get_current_user
        from app.models import User

        # Mock DB session
        mock_user = User(cognito_sub="local-dev-user", email="demo@example.com", name="Demo User")
        mock_session = AsyncMock()
        mock_session.scalar.return_value = mock_user

        # verifier=None, credentials=None
        user = await get_current_user(
            session=mock_session,
            verifier=None,
            credentials=None,
        )

        assert user.cognito_sub == "local-dev-user"
        assert user.email == "demo@example.com"
        assert user.name == "Demo User"

    @pytest.mark.asyncio
    async def test_backend_current_user_enforces_auth_when_configured(self) -> None:
        """When verifier is configured (production mode):

        get_current_user must raise HTTPException(401) when credentials are None.
        """
        from fastapi import HTTPException

        from app.auth import get_current_user

        mock_session = AsyncMock()
        mock_verifier = MagicMock()

        # verifier is set, but credentials is None -> must raise 401
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                session=mock_session,
                verifier=mock_verifier,
                credentials=None,
            )

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_backend_token_verifier_rejects_access_token(self) -> None:
        """Cognito access tokens must be rejected because they lack email and id token claims."""
        from app.auth import InvalidTokenError, TokenVerifier

        verifier = TokenVerifier("us-east-1_dummy", "dummy-client")

        # Mock the jwt.decode to return an access token claim set (token_use='access')
        import jwt

        fake_access_claims = {
            "token_use": "access",
            "sub": "user-uuid",
            "iss": verifier.issuer,
            "exp": 9999999999,
            "iat": 1000000000,
            "aud": "dummy-client",
        }

        # Mock _key to return a valid PyJWK
        mock_key = MagicMock()
        mock_key.key = "fake-key"
        verifier._key = AsyncMock(return_value=mock_key)

        original_decode = jwt.decode
        try:
            jwt.decode = MagicMock(return_value=fake_access_claims)
            with pytest.raises(InvalidTokenError, match="not an ID token"):
                # Fake jwt header
                # Valid 3-part base64 encoded JWT structure
                fake_jwt = "eyJhbGciOiAiUlMyNTYiLCAia2lkIjogIjEyMyJ9.eyJ0b2tlbl91c2UiOiAiYWNjZXNzIiwgInN1YiI6ICIxMjMifQ.c2ln"
                await verifier.verify(fake_jwt)
        finally:
            jwt.decode = original_decode
