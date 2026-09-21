"""Pydantic models for the auth + user-management API (spec 4.2/4.4)."""
from pydantic import BaseModel, Field, field_validator

# Kept as regexes rather than pulling in email-validator: this is a learning
# project and the spec only asks for "standard format" (spec 4.4).
USERNAME_RE = r"^[a-zA-Z0-9_]+$"
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# bcrypt rejects passwords longer than 72 bytes, so the cap is enforced here
# (422) instead of surfacing as a 500 from the hashing call.
PASSWORD_MAX = 72


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=USERNAME_RE)
    email: str = Field(..., min_length=3, max_length=254, pattern=EMAIL_RE)
    password: str = Field(..., min_length=8, max_length=PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    # Deliberately NOT min_length=8: a wrong short password must produce the
    # same 401 as a wrong long one, never a 422 (spec 4.4: no enumeration).
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20, max_length=256)


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=20)


class BanRequest(BaseModel):
    reason: str = Field("", max_length=500)


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
    status: str
    created_at: float


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
