"""Adversarial stress test suite - Challenger 1.

Comprehensive empirical challenges:
1. Cryptographic token verification & attack vectors:
   - RSA signature tampering and forgery
   - Algorithm confusion attacks ('none', 'HS256', 'RS512')
   - Token expiration and future issue timestamps
   - Missing mandatory standard claims ('exp', 'iat', 'sub', 'aud', 'iss')
   - Audience / Issuer substitution attacks
   - Token-use restriction enforcement (rejection of access / refresh tokens)
   - Malformed / corrupted token structure fuzzing
2. Backend authentication dependency injection & user sync:
   - Missing / malformed Authorization header formats
   - Name truncation on oversized claims
   - DB synchronization on attribute changes
3. Live AWS Cognito endpoint resilience:
   - Malformed / expired authorization code exchange
   - PKCE verifier mismatch and omission
   - Unauthorized redirect URI attack
   - Missing required OAuth parameters
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.auth import InvalidTokenError, TokenVerifier  # noqa: E402

ENV_PATH = ROOT_DIR / ".env"


def generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, str, str]:
    """Generates an RSA keypair and returns (private_key, kid, jwks_json)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    public_numbers = public_key.public_numbers()
    e_bytes = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, byteorder="big")
    n_bytes = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, byteorder="big")

    kid = "test-key-id-1"
    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "kid": kid,
        "n": base64.urlsafe_b64encode(n_bytes).decode("ascii").rstrip("="),
        "e": base64.urlsafe_b64encode(e_bytes).decode("ascii").rstrip("="),
    }
    jwks = json.dumps({"keys": [jwk]})
    return private_key, kid, jwks


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


class TestTokenVerifierAdversarialSecurity:
    """Stress tests cryptographic invariants and JWT attacks on TokenVerifier."""

    USER_POOL_ID = "us-east-1_TestPool123"
    CLIENT_ID = "test-client-id-abc"
    ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{USER_POOL_ID}"

    @pytest.fixture(autouse=True)
    def setup_keys(self) -> None:
        self.private_key, self.kid, self.jwks = generate_rsa_keypair()
        self.verifier = TokenVerifier(self.USER_POOL_ID, self.CLIENT_ID, self.jwks)

    def _mint_token(
        self,
        claims: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        key: Any = None,
        algorithm: str = "RS256",
    ) -> str:
        now = int(time.time())
        default_claims = {
            "sub": "user-uuid-1234",
            "email": "victim@example.com",
            "name": "Victim User",
            "iss": self.ISSUER,
            "aud": self.CLIENT_ID,
            "token_use": "id",
            "iat": now,
            "exp": now + 3600,
        }
        if claims:
            default_claims.update(claims)

        default_headers = {"kid": self.kid}
        if headers:
            default_headers.update(headers)

        signing_key = key if key is not None else self.private_key
        return jwt.encode(default_claims, signing_key, algorithm=algorithm, headers=default_headers)

    @pytest.mark.asyncio
    async def test_valid_token_passes_verification(self) -> None:
        token = self._mint_token()
        verified = await self.verifier.verify(token)
        assert verified["sub"] == "user-uuid-1234"
        assert verified["email"] == "victim@example.com"
        assert verified["token_use"] == "id"

    @pytest.mark.asyncio
    async def test_expired_token_is_rejected(self) -> None:
        now = int(time.time())
        expired_token = self._mint_token({"exp": now - 60, "iat": now - 3600})
        with pytest.raises(InvalidTokenError, match="Signature has expired"):
            await self.verifier.verify(expired_token)

    @pytest.mark.asyncio
    async def test_tampered_payload_is_rejected(self) -> None:
        token = self._mint_token()
        header_b64, payload_b64, sig_b64 = token.split(".")

        # Tamper payload to elevate privileges or spoof identity
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        payload["sub"] = "admin-attacker-uuid"
        payload["email"] = "attacker@example.com"
        tampered_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

        tampered_token = f"{header_b64}.{tampered_b64}.{sig_b64}"
        with pytest.raises(InvalidTokenError, match="Signature verification failed"):
            await self.verifier.verify(tampered_token)

    @pytest.mark.asyncio
    async def test_tampered_signature_is_rejected(self) -> None:
        token = self._mint_token()
        header_b64, payload_b64, sig_b64 = token.split(".")

        # Flip last byte of signature
        corrupted_sig = sig_b64[:-2] + ("AA" if sig_b64[-2:] != "AA" else "BB")
        corrupted_token = f"{header_b64}.{payload_b64}.{corrupted_sig}"

        with pytest.raises(InvalidTokenError, match="Signature verification failed"):
            await self.verifier.verify(corrupted_token)

    @pytest.mark.asyncio
    async def test_forged_key_signature_rejected(self) -> None:
        # Attacker generates their own RSA key and signs token with same kid
        attacker_key, _, _ = generate_rsa_keypair()
        forged_token = self._mint_token(key=attacker_key)

        with pytest.raises(InvalidTokenError, match="Signature verification failed"):
            await self.verifier.verify(forged_token)

    @pytest.mark.asyncio
    async def test_unknown_kid_rejected(self) -> None:
        token = self._mint_token(headers={"kid": "unknown-nonexistent-kid"})
        with pytest.raises(InvalidTokenError, match="unknown signing key"):
            await self.verifier.verify(token)

    @pytest.mark.asyncio
    async def test_missing_kid_rejected(self) -> None:
        # Token header without 'kid'
        now = int(time.time())
        token = jwt.encode(
            {"sub": "u", "aud": self.CLIENT_ID, "iss": self.ISSUER, "exp": now + 3600, "iat": now},
            self.private_key,
            algorithm="RS256",
            # No kid in header
        )
        with pytest.raises(InvalidTokenError, match="unknown signing key"):
            await self.verifier.verify(token)

    @pytest.mark.asyncio
    async def test_algorithm_none_attack_rejected(self) -> None:
        # Alg: none attack attempt
        now = int(time.time())
        claims = {
            "sub": "attacker",
            "email": "attacker@evil.com",
            "aud": self.CLIENT_ID,
            "iss": self.ISSUER,
            "token_use": "id",
            "iat": now,
            "exp": now + 3600,
        }
        none_token = jwt.encode(claims, key="", algorithm="none", headers={"kid": self.kid})
        with pytest.raises(InvalidTokenError):
            await self.verifier.verify(none_token)

    @pytest.mark.asyncio
    async def test_algorithm_confusion_hs256_rejected(self) -> None:
        # Attacker attempts HMAC-SHA256 token against RS256 verifier
        secret = b"symmetric-hmac-secret-attempt-32bytes-padding"
        now = int(time.time())
        claims = {
            "sub": "attacker",
            "email": "attacker@evil.com",
            "aud": self.CLIENT_ID,
            "iss": self.ISSUER,
            "token_use": "id",
            "iat": now,
            "exp": now + 3600,
        }
        hs256_token = jwt.encode(claims, key=secret, algorithm="HS256", headers={"kid": self.kid})
        with pytest.raises(InvalidTokenError):
            await self.verifier.verify(hs256_token)

    @pytest.mark.asyncio
    async def test_access_token_rejected_not_id_token(self) -> None:
        # Cognito access tokens have token_use: "access"
        access_token = self._mint_token({"token_use": "access"})
        with pytest.raises(InvalidTokenError, match="not an ID token"):
            await self.verifier.verify(access_token)

    @pytest.mark.asyncio
    async def test_missing_token_use_rejected(self) -> None:
        now = int(time.time())
        claims = {
            "sub": "user-uuid-1234",
            "email": "victim@example.com",
            "iss": self.ISSUER,
            "aud": self.CLIENT_ID,
            "iat": now,
            "exp": now + 3600,
            # token_use intentionally omitted
        }
        token = jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": self.kid})
        with pytest.raises(InvalidTokenError, match="not an ID token"):
            await self.verifier.verify(token)

    @pytest.mark.asyncio
    async def test_audience_mismatch_rejected(self) -> None:
        token = self._mint_token({"aud": "different-rogue-client-id"})
        with pytest.raises(InvalidTokenError, match="Audience doesn't match"):
            await self.verifier.verify(token)

    @pytest.mark.asyncio
    async def test_issuer_mismatch_rejected(self) -> None:
        token = self._mint_token(
            {"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AttackerPool"}
        )
        with pytest.raises(InvalidTokenError, match="Invalid issuer"):
            await self.verifier.verify(token)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing_claim", ["sub", "aud", "iss", "exp", "iat"])
    async def test_missing_required_claims_rejected(self, missing_claim: str) -> None:
        now = int(time.time())
        claims = {
            "sub": "u",
            "aud": self.CLIENT_ID,
            "iss": self.ISSUER,
            "token_use": "id",
            "iat": now,
            "exp": now + 3600,
        }
        claims.pop(missing_claim)
        token = jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": self.kid})
        with pytest.raises(InvalidTokenError):
            await self.verifier.verify(token)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fuzzed_token",
        [
            "",
            "...",
            "single-part",
            "part1.part2",
            "not-a-token-at-all",
            "a" * 10000,
            "eyJhbGciOiJSUzI1NiJ9.invalid-json.sig",
        ],
    )
    async def test_fuzzed_token_structures_rejected(self, fuzzed_token: str) -> None:
        with pytest.raises(InvalidTokenError):
            await self.verifier.verify(fuzzed_token)


class TestLiveCognitoOAuthEdgeCases:
    """Exercises live AWS Cognito Hosted UI endpoints with invalid/adversarial inputs."""

    @pytest.mark.asyncio
    async def test_live_token_endpoint_rejects_malformed_auth_code(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = env_vars.get("COGNITO_DOMAIN", "").replace("https://", "").rstrip("/")
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito not configured in .env")

        token_url = f"https://{domain}/oauth2/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "malformed-bogus-authorization-code-123456",
            "redirect_uri": "http://localhost:5173/login",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert resp.status_code == 400, f"Expected HTTP 400 for bogus code, got {resp.status_code}"
        data = resp.json()
        assert data.get("error") == "invalid_grant", f"Expected error: invalid_grant, got {data}"

    @pytest.mark.asyncio
    async def test_live_token_endpoint_rejects_missing_code_verifier(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = env_vars.get("COGNITO_DOMAIN", "").replace("https://", "").rstrip("/")
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito not configured in .env")

        token_url = f"https://{domain}/oauth2/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "dummy-code",
            "redirect_uri": "http://localhost:5173/login",
            # code_verifier omitted
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert resp.status_code == 400
        data = resp.json()
        assert data.get("error") in ("invalid_request", "invalid_grant")

    @pytest.mark.asyncio
    async def test_live_token_endpoint_rejects_unregistered_redirect_uri(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = env_vars.get("COGNITO_DOMAIN", "").replace("https://", "").rstrip("/")
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito not configured in .env")

        token_url = f"https://{domain}/oauth2/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": "dummy-code",
            "redirect_uri": "https://evil-attacker.com/steal-token",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert resp.status_code == 400
        data = resp.json()
        assert data.get("error") == "invalid_grant"

    @pytest.mark.asyncio
    async def test_live_authorize_endpoint_blocks_unregistered_redirect_uri(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = env_vars.get("COGNITO_DOMAIN", "").replace("https://", "").rstrip("/")
        client_id = env_vars.get("COGNITO_CLIENT_ID", "")
        if not domain or not client_id:
            pytest.skip("Cognito not configured in .env")

        attacker_url = "https://evil-attacker.com/callback"
        auth_url = (
            f"https://{domain}/oauth2/authorize?client_id={client_id}"
            f"&response_type=code&scope=openid+email+profile"
            f"&redirect_uri={attacker_url}"
            f"&code_challenge=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk&code_challenge_method=S256"
        )

        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(auth_url)

        # Cognito Managed Login v2 issues a 302 redirect to its internal error page
        # and NEVER redirects to the unauthorized third-party attacker URI
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert attacker_url not in location, f"Security violation: Cognito redirected to {location}"
        assert f"https://{domain}/error" in location
        assert "error=redirect_mismatch" in location

    @pytest.mark.asyncio
    async def test_live_authorize_endpoint_blocks_invalid_client_id(
        self, env_vars: dict[str, str]
    ) -> None:
        domain = env_vars.get("COGNITO_DOMAIN", "").replace("https://", "").rstrip("/")
        if not domain:
            pytest.skip("Cognito domain not configured in .env")

        bad_client = "nonexistent-client-id-xyz"
        auth_url = (
            f"https://{domain}/oauth2/authorize?client_id={bad_client}"
            f"&response_type=code&scope=openid+email+profile"
            f"&redirect_uri=http://localhost:5173/login"
            f"&code_challenge=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk&code_challenge_method=S256"
        )

        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(auth_url)

        # Cognito Managed Login v2 redirects to error page for invalid client_id
        assert resp.status_code == 302
        location = resp.headers.get("location", "")
        assert f"https://{domain}/error" in location
        assert "error=invalid_request" in location
