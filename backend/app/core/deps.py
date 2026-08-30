"""Shared FastAPI dependencies: DB session, current user, role guards."""

from __future__ import annotations

import ipaddress
import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.enums import UserRole
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.logging import user_id_ctx
from app.core.schemas import PageParams
from app.core.security import decode_access_token
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository

# auto_error=False so an anonymous request reaches `current_user_optional`
# instead of being rejected by the security scheme itself.
bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def current_user(db: DbSession, credentials: Credentials) -> User:
    if credentials is None:
        raise AuthenticationError()
    payload = decode_access_token(credentials.credentials)
    user = UserRepository(db).get(uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("Account unavailable.")
    user_id_ctx.set(str(user.id))
    return user


def current_user_optional(db: DbSession, credentials: Credentials) -> User | None:
    """For endpoints that personalise when signed in but still work anonymously
    (movie listings, semantic search, recommendations)."""
    if credentials is None:
        return None
    try:
        return current_user(db, credentials)
    except AuthenticationError:
        return None


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(current_user_optional)]


def require_roles(*roles: UserRole):
    """Route guard factory: ``Depends(require_roles(UserRole.ADMIN))``."""

    allowed = set(roles)

    def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError(
                f"This action requires one of: {', '.join(sorted(r.value for r in allowed))}."
            )
        return user

    return _guard


OperatorUser = Annotated[
    User, Depends(require_roles(UserRole.CINEMA_OPERATOR, UserRole.ADMIN))
]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def pagination(page: int = 1, page_size: int = 20) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(pagination)]


def _parse_ip(value: str | None) -> str | None:
    """Return `value` only if it is a real IP address.

    ``ip_address`` is a Postgres INET column, so anything that is not a valid
    address raises a DataError and turns a login into a 500. Test clients send
    "testclient", and a misconfigured proxy can send a hostname or a comma-joined
    X-Forwarded-For chain -- none of which should be able to break sign-in.
    """
    if not value:
        return None
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    return value.strip()


def client_context(request: Request) -> dict[str, str | None]:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip_address": _parse_ip(request.client.host if request.client else None),
    }


ClientContext = Annotated[dict, Depends(client_context)]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
