#Support assistant endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.assistant.schemas import AskRequest, AskResponse
from app.modules.assistant.service import build_service

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    """
"""Answer a customer question from the support knowledge base.

    Open to guests on purpose: the questions it answers -- refund windows, what
    IMAX costs, whether outside food is allowed -- are the ones people ask
    *before* they have an account, and requiring a login to read published policy
    would be user-hostile. It reads no per-user data and holds no conversation
    state, so there is nothing here to leak.
    """
""" return build_service().ask(payload.question)
"""
from fastapi import APIRouter
from pydantic import BaseModel
from .retriever import retrieve

router = APIRouter(prefix="/assistant", tags=["assistant"])

class AskRequest(BaseModel):
    question: str

#GROUNDED_THRESHOLD = 0.8   # tune by printing distances for good/bad questions
GROUNDED_THRESHOLD = 1.20   # Raised from 0.8 to accommodate sentence-transformers L2 distances

@router.post("/ask")
def ask(req: AskRequest):
    hits = retrieve(req.question, k=3)
    grounded = bool(hits) and hits[0]["distance"] < GROUNDED_THRESHOLD

    if grounded:
        answer = hits[0]["text"]          # best chunk IS the answer
    else:
        answer = ("I couldn't find this in our help centre. "
                  "Try rephrasing, or contact support.")

    return {
        "answer": answer,
        "sources": [{"section": h["section"], "excerpt": h["text"][:150]} for h in hits],
        "suggestions": [],
        "grounded": grounded,
    }