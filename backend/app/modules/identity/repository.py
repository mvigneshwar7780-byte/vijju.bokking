"""Identity persistence. The only place that writes `users`/`refresh_tokens`.

Repositories hold *queries*, not policy. They never commit -- the caller owns
the transaction so a whole request stays atomic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.identity.models import RefreshToken, User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def email_exists(self, email: str) -> bool:
        stmt = select(User.id).where(User.email == email.strip().lower())
        return self.db.execute(stmt).first() is not None

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user

    def touch_login(self, user: User) -> None:
        user.last_login_at = datetime.now(UTC)
        self.db.flush()


class RefreshTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        self.db.flush()
        return token

    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(UTC)
        self.db.flush()

    def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Used when a rotated token is replayed -- assume the chain is stolen."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return int(self.db.execute(stmt).rowcount or 0)

    def purge_expired(self, before: datetime | None = None) -> int:
        from sqlalchemy import delete

        cutoff = before or datetime.now(UTC)
        stmt = delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        return int(self.db.execute(stmt).rowcount or 0)
