"""Identity policy: registration, login, refresh-token rotation, profile."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import UserRole
from app.core.errors import AuthenticationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.modules.identity.models import RefreshToken, User
from app.modules.identity.repository import RefreshTokenRepository, UserRepository
from app.modules.identity.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenPair,
    UpdateProfileRequest,
)

logger = get_logger(__name__)


class IdentityService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.tokens = RefreshTokenRepository(db)

    # ------------------------------------------------------------ register ---
    def register(self, payload: RegisterRequest) -> User:
        if self.users.email_exists(payload.email):
            raise ConflictError(
                "An account with that email already exists.",
                code="EMAIL_TAKEN",
            )
        user = User(
            email=payload.email,
            full_name=payload.full_name.strip(),
            phone=payload.phone,
            password_hash=hash_password(payload.password),
            role=UserRole.CUSTOMER,
        )
        self.users.add(user)
        logger.info("user_registered", user_id=str(user.id), email=user.email)
        return user

    # --------------------------------------------------------------- login ---
    def authenticate(self, payload: LoginRequest) -> User:
        user = self.users.get_by_email(payload.email)
        # Constant-ish work whether or not the user exists, so response timing
        # does not reveal which emails are registered.
        if user is None:
            hash_password(payload.password)
            raise AuthenticationError("Incorrect email or password.")
        if not verify_password(payload.password, user.password_hash):
            raise AuthenticationError("Incorrect email or password.")
        if not user.is_active:
            raise AuthenticationError("This account has been deactivated.")

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(payload.password)
        self.users.touch_login(user)
        return user

    # -------------------------------------------------------------- tokens ---
    def issue_tokens(
        self,
        user: User,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
        rotated_from: RefreshToken | None = None,
    ) -> TokenPair:
        access, expires_at = create_access_token(user.id, role=user.role.value)
        raw_refresh, refresh_hash = generate_refresh_token()
        self.tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=refresh_hash,
                expires_at=datetime.now(UTC)
                + timedelta(days=settings.refresh_token_ttl_days),
                user_agent=(user_agent or "")[:400] or None,
                ip_address=ip_address,
                rotated_from_id=rotated_from.id if rotated_from else None,
            )
        )
        return TokenPair(
            access_token=access, refresh_token=raw_refresh, expires_at=expires_at
        )

    def refresh(
        self,
        raw_refresh: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        stored = self.tokens.get_by_hash(hash_refresh_token(raw_refresh))
        if stored is None:
            raise AuthenticationError("Invalid refresh token.")

        if stored.revoked_at is not None:
            # A revoked token being presented means either a stale client or a
            # stolen token being replayed. We cannot tell them apart, so we take
            # the safe option and kill every session for that user.
            revoked = self.tokens.revoke_all_for_user(stored.user_id)
            logger.warning(
                "refresh_token_replay",
                user_id=str(stored.user_id),
                sessions_revoked=revoked,
            )
            raise AuthenticationError("Session revoked. Please sign in again.")

        if stored.expires_at <= datetime.now(UTC):
            raise AuthenticationError("Refresh token expired. Please sign in again.")

        user = self.users.get(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account unavailable.")

        # Rotate: the presented token is burnt, a fresh pair is issued.
        self.tokens.revoke(stored)
        return self.issue_tokens(
            user, user_agent=user_agent, ip_address=ip_address, rotated_from=stored
        )

    def logout(self, raw_refresh: str) -> None:
        stored = self.tokens.get_by_hash(hash_refresh_token(raw_refresh))
        if stored is not None and stored.revoked_at is None:
            self.tokens.revoke(stored)

    # ------------------------------------------------------------- profile ---
    def get_user(self, user_id: uuid.UUID) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    def update_profile(self, user: User, payload: UpdateProfileRequest) -> User:
        if payload.full_name is not None:
            user.full_name = payload.full_name.strip()
        if payload.phone is not None:
            user.phone = payload.phone
        if payload.default_city_id is not None:
            user.default_city_id = payload.default_city_id
        if payload.preferences is not None:
            # Merge rather than replace: a partial update must not silently drop
            # keys the client did not know about.
            user.preferences = {**(user.preferences or {}), **payload.preferences}
        self.db.flush()
        return user
