"""Cognito authentication. Every API route except /api/health needs a Cognito ID token:
`Authorization: Bearer <id token>`. The first request of a new user creates their row in
`users`; later requests keep its email and name in sync with the token."""

import asyncio
import time
import urllib.request
from functools import cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import SessionDep
from app.models import User

# Unknown key ids trigger a fresh download of the keys (Cognito rotated them), at most this often.
JWKS_REFRESH_SECONDS = 60


class InvalidTokenError(Exception):
    pass


class TokenVerifier:
    """Checks the signature, issuer, audience and expiry of Cognito ID tokens."""

    def __init__(self, user_pool_id: str, client_id: str, jwks: str = "") -> None:
        region = user_pool_id.split("_", 1)[0]
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.client_id = client_id
        # Keys given up front (AWS) are final: the function cannot download new ones anyway.
        self._fixed = bool(jwks)
        self._jwks = jwt.PyJWKSet.from_json(jwks) if jwks else None
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    def _download(self) -> jwt.PyJWKSet:
        url = f"{self.issuer}/.well-known/jwks.json"
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 (fixed https URL)
            return jwt.PyJWKSet.from_json(response.read().decode())

    async def _key(self, kid: str) -> jwt.PyJWK | None:
        async with self._lock:
            stale = time.monotonic() - self._fetched_at > JWKS_REFRESH_SECONDS
            if self._jwks is None or (not self._fixed and stale and kid not in self._kids()):
                self._jwks = await asyncio.to_thread(self._download)
                self._fetched_at = time.monotonic()
        return next((key for key in self._jwks.keys if key.key_id == kid), None)

    def _kids(self) -> set[str]:
        return {key.key_id for key in self._jwks.keys} if self._jwks else set()

    async def verify(self, token: str) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = await self._key(kid) if kid else None
            if key is None:
                raise InvalidTokenError("unknown signing key")
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as error:
            raise InvalidTokenError(str(error)) from error
        # Access tokens have no audience and no email; only ID tokens are accepted.
        if claims.get("token_use") != "id":
            raise InvalidTokenError("not an ID token")
        return claims


@cache
def get_verifier() -> TokenVerifier | None:
    if not settings.cognito_user_pool_id or not settings.cognito_client_id:
        return None
    return TokenVerifier(
        settings.cognito_user_pool_id, settings.cognito_client_id, settings.cognito_jwks
    )


bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_current_user(
    session: SessionDep,
    verifier: Annotated[TokenVerifier | None, Depends(get_verifier)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if verifier is None:
        # Local development without Cognito configured: fallback to a demo user
        demo_sub = "local-dev-user"
        user = await session.scalar(select(User).where(User.cognito_sub == demo_sub))
        if user is None:
            user = User(cognito_sub=demo_sub, email="demo@example.com", name="Demo User")
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                user = await session.scalar(select(User).where(User.cognito_sub == demo_sub))
        return user

    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        claims = await verifier.verify(credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized("Invalid or expired token") from None

    email = claims.get("email", "")
    name = (claims.get("name") or email.split("@")[0])[:100]
    user = await session.scalar(select(User).where(User.cognito_sub == claims["sub"]))
    if user is None:
        user = User(cognito_sub=claims["sub"], email=email, name=name)
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # A parallel first request created the row; use that one.
            await session.rollback()
            user = await session.scalar(select(User).where(User.cognito_sub == claims["sub"]))
    elif (user.email, user.name) != (email, name):
        user.email, user.name = email, name
        await session.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
