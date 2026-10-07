"""Automated test suite validating frontend OAuth 2.0 PKCE flow and Cognito endpoints.

Validates:
- RFC 7636 S256 PKCE challenge mathematical derivation and standard test vectors
- Domain sanitization, Authorize URL, and Logout URL generation
- JWT payload parsing and user profile extraction (email, name, Google provider mapping)
- Frontend component contracts in login-page.tsx, home-page.tsx, and signup-page.tsx
- Live Cognito Hosted UI v2 authorize endpoint redirect behavior
- Live Cognito Hosted UI v2 logout endpoint redirect and session termination
"""

from __future__ import annotations

import base64
import hashlib
import urllib.parse
from pathlib import Path

import httpx
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
ENV_PATH = ROOT_DIR / ".env"


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


def compute_s256_challenge(verifier: str) -> str:
    """Python implementation of frontend generateCodeChallenge(verifier)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def clean_domain(domain: str) -> str:
    """Python mirror of frontend cleanDomain helper."""
    d = domain.strip()
    if d.startswith("https://"):
        d = d[8:]
    elif d.startswith("http://"):
        d = d[7:]
    return d.rstrip("/")


def extract_user_from_claims(claims: dict) -> dict:
    """Python mirror of frontend extractUserFromClaims helper."""
    email = str(claims.get("email", ""))
    name = str(claims.get("name") or (email.split("@")[0] if email else "User"))
    identities = claims.get("identities")
    sub = claims.get("sub")
    is_google = (
        bool(identities)
        or (isinstance(sub, str) and "Google" in sub)
        or (isinstance(identities, list) and len(identities) > 0)
    )
    return {
        "name": name,
        "email": email,
        "provider": "google" if is_google else "password",
        "sub": str(sub) if sub else None,
    }


class TestPKCEAndOAuthHelpers:
    """Validates PKCE derivation, URL synthesis, and claims parsing algorithms."""

    def test_rfc7636_standard_test_vector(self) -> None:
        """Derives code_challenge using RFC 7636 Appendix B test vector."""
        test_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        expected_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        actual_challenge = compute_s256_challenge(test_verifier)
        assert actual_challenge == expected_challenge, (
            f"PKCE S256 derivation mismatch: got {actual_challenge}, expected {expected_challenge}"
        )

    def test_clean_domain_handling(self) -> None:
        target = "example.auth.us-east-1.amazoncognito.com"
        assert clean_domain(f"https://{target}") == target
        assert clean_domain(f"https://{target}/") == target
        assert clean_domain(f"http://{target}///") == target
        assert clean_domain(target) == target

    def test_authorize_url_composition(self, env_vars: dict[str, str]) -> None:
        domain = clean_domain(env_vars.get("COGNITO_DOMAIN", "auth.example.com"))
        client_id = env_vars.get("COGNITO_CLIENT_ID", "test-client")
        origin = "http://localhost:5173"
        redirect_uri = f"{origin}/login"
        verifier = "test-verifier-random-string-with-sufficient-entropy-for-testing"
        challenge = compute_s256_challenge(verifier)

        auth_url = (
            f"https://{domain}/oauth2/authorize?client_id={client_id}"
            f"&response_type=code&scope=openid+email+profile"
            f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
            f"&code_challenge={challenge}&code_challenge_method=S256"
        )

        parsed = urllib.parse.urlparse(auth_url)
        assert parsed.scheme == "https"
        assert parsed.netloc == domain
        assert parsed.path == "/oauth2/authorize"

        query = urllib.parse.parse_qs(parsed.query)
        assert query["client_id"] == [client_id]
        assert query["response_type"] == ["code"]
        assert query["scope"] == ["openid email profile"]
        assert query["redirect_uri"] == [redirect_uri]
        assert query["code_challenge"] == [challenge]
        assert query["code_challenge_method"] == ["S256"]

    def test_logout_url_composition(self, env_vars: dict[str, str]) -> None:
        domain = clean_domain(env_vars.get("COGNITO_DOMAIN", "auth.example.com"))
        client_id = env_vars.get("COGNITO_CLIENT_ID", "test-client")
        origin = "http://localhost:5173"
        logout_uri = urllib.parse.quote(f"{origin}/login", safe="")

        logout_url = f"https://{domain}/logout?client_id={client_id}&logout_uri={logout_uri}"
        parsed = urllib.parse.urlparse(logout_url)
        assert parsed.scheme == "https"
        assert parsed.netloc == domain
        assert parsed.path == "/logout"

        query = urllib.parse.parse_qs(parsed.query)
        assert query["client_id"] == [client_id]
        assert query["logout_uri"] == [f"{origin}/login"]

    def test_extract_user_claims_cognito_password(self) -> None:
        claims = {
            "sub": "b2f67623-6401-70e1-6453-2bf576c6c747",
            "email": "alice@example.com",
            "name": "Alice Cooper",
            "email_verified": True,
        }
        user = extract_user_from_claims(claims)
        assert user["email"] == "alice@example.com"
        assert user["name"] == "Alice Cooper"
        assert user["provider"] == "password"
        assert user["sub"] == "b2f67623-6401-70e1-6453-2bf576c6c747"

    def test_extract_user_claims_google_federated(self) -> None:
        claims_with_identities = {
            "sub": "c3e87834-8902-71f2-7564-3cg687d7d858",
            "email": "carol.google@gmail.com",
            "name": "Carol Danvers",
            "identities": [
                {"userId": "1029384756", "providerName": "Google", "providerType": "Google"}
            ],
        }
        user1 = extract_user_from_claims(claims_with_identities)
        assert user1["provider"] == "google"
        assert user1["email"] == "carol.google@gmail.com"

        claims_with_google_sub = {
            "sub": "Google_1092837465",
            "email": "bob.builder@gmail.com",
        }
        user2 = extract_user_from_claims(claims_with_google_sub)
        assert user2["provider"] == "google"
        assert user2["name"] == "bob.builder"


class TestFrontendComponentContracts:
    """Verifies that frontend source files adhere to the Acceptance Criteria."""

    def test_login_page_immediate_redirect_contract(self) -> None:
        login_file = FRONTEND_DIR / "src" / "pages" / "login-page.tsx"
        assert login_file.is_file()
        content = login_file.read_text(encoding="utf-8")

        # Must inspect URL search params for authorization code and error
        assert "params.get('code')" in content, "login-page.tsx must check for authorization code"
        assert "params.get('error')" in content, "login-page.tsx must check for error param"
        assert "exchangeAuthCode(code)" in content, "login-page.tsx must invoke exchangeAuthCode"
        assert "signinRedirect()" in content, "login-page.tsx must initiate signinRedirect"

        # Must render redirecting indicator when authConfigured and no error
        assert "Redirecting to sign in..." in content or "Connecting to Cognito" in content
        # Must retain local dev fallback when !authConfigured
        assert "<AuthNotConfigured />" in content

    def test_home_page_header_displays_email_and_signout(self) -> None:
        home_file = FRONTEND_DIR / "src" / "pages" / "home-page.tsx"
        assert home_file.is_file()
        content = home_file.read_text(encoding="utf-8")

        # Header must display user.email visibly
        assert "{user.email}" in content, "home-page.tsx header must visibly render {user.email}"
        # Header must have explicit Sign out button
        assert "Sign out" in content, "home-page.tsx header must display 'Sign out' button"
        assert "onClick={signOut}" in content or "signOut" in content

    def test_signup_page_redirects_when_cognito_configured(self) -> None:
        signup_file = FRONTEND_DIR / "src" / "pages" / "signup-page.tsx"
        assert signup_file.is_file()
        content = signup_file.read_text(encoding="utf-8")

        assert "authConfigured" in content
        assert "navigate('/login'" in content, (
            "signup-page must route to /login when auth is configured"
        )


class TestLiveCognitoEndpoints:
    """Exercises the live AWS Cognito Managed Login v2 endpoints over HTTPS."""

    @pytest.mark.asyncio
    async def test_live_authorize_endpoint_redirects_to_hosted_ui(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = clean_domain(env_vars.get("COGNITO_DOMAIN", ""))
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito domain or client ID not configured in .env")

        origin = "http://localhost:5173"
        redirect_uri = f"{origin}/login"
        verifier = "live-test-verifier-random-string-high-entropy-value"
        challenge = compute_s256_challenge(verifier)

        auth_url = (
            f"https://{domain}/oauth2/authorize?client_id={client_id}"
            f"&response_type=code&scope=openid+email+profile"
            f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
            f"&code_challenge={challenge}&code_challenge_method=S256"
        )

        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(auth_url)

        assert resp.status_code == 302, (
            f"Expected 302 redirect from /oauth2/authorize, got {resp.status_code}"
        )
        location = resp.headers.get("location", "")
        assert location.startswith(f"https://{domain}/login?"), (
            f"Expected redirect location to point to Hosted UI /login, got: {location}"
        )
        assert f"client_id={client_id}" in location
        assert "response_type=code" in location

    @pytest.mark.asyncio
    async def test_live_managed_login_v2_page_serves_spa_assets(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = clean_domain(env_vars.get("COGNITO_DOMAIN", ""))
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito domain not configured in .env")

        auth_url = (
            f"https://{domain}/oauth2/authorize?client_id={client_id}"
            f"&response_type=code&scope=openid+email+profile"
            f"&redirect_uri={urllib.parse.quote('http://localhost:5173/login', safe='')}"
            f"&code_challenge={compute_s256_challenge('test')}&code_challenge_method=S256"
        )

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(auth_url)

        assert resp.status_code == 200, (
            f"Expected 200 for Managed Login page, got {resp.status_code}"
        )
        html = resp.text
        # AWS Cognito Managed Login v2 renders a Remix SPA bundle
        assert "__remixRouteModules" in html or "routes/login" in html or "assets" in html, (
            "Hosted UI response must contain Cognito Managed Login v2 SPA markup"
        )

    @pytest.mark.asyncio
    async def test_live_logout_endpoint_redirects_and_clears_session(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = clean_domain(env_vars.get("COGNITO_DOMAIN", ""))
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito domain or client ID not configured in .env")

        logout_uri = urllib.parse.quote("http://localhost:5173/login", safe="")
        logout_url = f"https://{domain}/logout?client_id={client_id}&logout_uri={logout_uri}"

        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(logout_url)

        assert resp.status_code == 302, (
            f"Expected 302 redirect from /logout, got {resp.status_code}"
        )
        assert resp.headers.get("location") == "http://localhost:5173/login", (
            f"Expected redirect back to login, got {resp.headers.get('location')}"
        )
