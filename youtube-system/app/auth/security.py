"""Pure crypto/token helpers: bcrypt hashing, JWT codec, role levels.

No IO in this module - it never touches SQLite or Redis. That keeps it
directly verifiable and preserves the one-way dependency rule
(router -> service -> security, dependencies -> security).
"""
import hashlib
import secrets
import time

import bcrypt
import jwt

from app.config import config

# Role hierarchy (spec 1.3). Higher level implicitly includes lower ones;
# the frontend keeps an identically-named copy in src/auth.js.
ROLES = ("user", "creator", "moderator", "admin")
ROLE_LEVEL = {"user": 1, "creator": 2, "moderator": 3, "admin": 4}

_ALGO = "HS256"


class InvalidTokenError(Exception):
    """Access token cannot be trusted: bad signature, expired, or wrong shape."""


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False  # malformed hash in DB - treat as wrong password


def create_access_token(user_id: str, username: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + config.access_token_ttl,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=_ALGO)


def decode_access_token(token: str) -> dict:
    """Verify signature + expiry locally. Never queries the DB or Redis -
    that is the whole point of the stateless access token (spec 2.1)."""
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=[_ALGO])
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    if payload.get("type") != "access" or not payload.get("sub"):
        raise InvalidTokenError("not an access token")
    return payload


def make_refresh_token(user_id: str) -> str:
    """Opaque random string prefixed with the owner id.

    The prefix is what makes replay protection possible (spec 2.2/2.3): when a
    submitted token is absent from Redis we must still know whose sessions to
    revoke, and the client only sends the token itself.
    """
    return f"{user_id}.{secrets.token_urlsafe(48)}"


def split_refresh_token(token: str) -> str | None:
    """Return the owning user_id, or None if the token is malformed."""
    user_id, sep, _ = token.partition(".")
    return user_id if sep and user_id else None


def hash_token(token: str) -> str:
    """Only the SHA-256 of a refresh token is ever stored (spec 2.2)."""
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_key(user_id: str, token: str) -> str:
    return f"refresh:{user_id}:{hash_token(token)}"


def refresh_prefix(user_id: str) -> str:
    return f"refresh:{user_id}:"


def used_key(token: str) -> str:
    """Tombstone marking a refresh token as already rotated away.

    Lets refresh() tell a genuine replay (a token we really issued and then
    rotated) apart from random garbage: mass-revocation fires only on a real
    replay, so a stranger cannot evict a victim by guessing their user_id."""
    return f"refresh:used:{hash_token(token)}"


def ban_key(user_id: str) -> str:
    """Redis key marking a user as banned. get_current_user checks EXISTS on it
    (one O(1) GET, no DB) so a ban revokes even a live access token immediately
    (spec 2.5)."""
    return f"auth:ban:{user_id}"
