"""Auth and profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import ClientContext, CurrentUser, DbSession
from app.core.schemas import OkResponse
from app.modules.identity.schemas import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UpdateProfileRequest,
    UserOut,
)
from app.modules.identity.service import IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])
profile_router = APIRouter(prefix="/me", tags=["profile"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession, ctx: ClientContext) -> AuthResponse:
    service = IdentityService(db)
    user = service.register(payload)
    tokens = service.issue_tokens(user, **ctx)
    db.commit()
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: DbSession, ctx: ClientContext) -> AuthResponse:
    service = IdentityService(db)
    user = service.authenticate(payload)
    tokens = service.issue_tokens(user, **ctx)
    db.commit()
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession, ctx: ClientContext) -> TokenPair:
    tokens = IdentityService(db).refresh(payload.refresh_token, **ctx)
    db.commit()
    return tokens


@router.post("/logout", response_model=OkResponse)
def logout(payload: RefreshRequest, db: DbSession) -> OkResponse:
    IdentityService(db).logout(payload.refresh_token)
    db.commit()
    return OkResponse(message="Signed out.")


@profile_router.get("", response_model=UserOut)
def get_profile(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@profile_router.patch("", response_model=UserOut)
def update_profile(
    payload: UpdateProfileRequest, user: CurrentUser, db: DbSession
) -> UserOut:
    updated = IdentityService(db).update_profile(user, payload)
    db.commit()
    return UserOut.model_validate(updated)
