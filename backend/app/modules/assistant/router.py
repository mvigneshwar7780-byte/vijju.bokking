"""Support assistant endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.assistant.schemas import AskRequest, AskResponse
from app.modules.assistant.service import build_service

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    """Answer a customer question from the support knowledge base.

    Open to guests on purpose: the questions it answers -- refund windows, what
    IMAX costs, whether outside food is allowed -- are the ones people ask
    *before* they have an account, and requiring a login to read published policy
    would be user-hostile. It reads no per-user data and holds no conversation
    state, so there is nothing here to leak.
    """
    return build_service().ask(payload.question)
