"""Identity request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.schemas import APIModel
from app.core.enums import UserRole

Password = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    full_name: Annotated[str, Field(min_length=2, max_length=120)]
    phone: Annotated[str | None, Field(max_length=20)] = None

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        # Deliberately modest: length is what matters most, and a learning app
        # should not fight the developer at the login screen.
        if v.isdigit() or v.isalpha():
            raise ValueError("Password must mix letters with numbers or symbols.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserOut(APIModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    default_city_id: uuid.UUID | None
    preferences: dict
    created_at: datetime


class AuthResponse(APIModel):
    user: UserOut
    tokens: TokenPair


class UpdateProfileRequest(BaseModel):
    full_name: Annotated[str | None, Field(min_length=2, max_length=120)] = None
    phone: Annotated[str | None, Field(max_length=20)] = None
    default_city_id: uuid.UUID | None = None
    preferences: dict | None = None
