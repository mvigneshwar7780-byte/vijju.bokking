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
import os
from fastapi import APIRouter
from dotenv import load_dotenv
from pydantic import BaseModel
from app.modules.assistant.service import build_service
from app.modules.assistant.schemas import AskRequest, AskResponse
from google import genai
from google.genai import types
from google.genai.errors import ServerError
load_dotenv()  # Load environment variables from .env file
#G_API_KEY = os.getenv("GEMINI_API_KEY")
#api_key = os.getenv("AQ.Ab8RN6K0jziso02WEgWuUde589qBAmuRlQRiABfyUf3NIju5ug")
#client = genai.Client(api_key=G_API_KEY)
GEMINI_API_KEY = "AQ.Ab8RN6K0jziso02WEgWuUde589qBAmuRlQRiABfyUf3NIju5ug"
client = genai.Client(api_key=GEMINI_API_KEY)

# The retriever imports lancedb + sentence-transformers, which are not in
# requirements.txt. A plain `import` here runs while main.py is still importing
# routers, so on a machine without those packages it raised ModuleNotFoundError
# and NO router loaded at all -- including the catalogue. The site came up with
# an empty movie list because the whole API was dead.
#
# Buying a ticket must not depend on the help centre being installed. The import
# is attempted once and its failure remembered, so the API always boots and only
# /assistant/ask degrades.
try:
    from .retriever import retrieve

    _RETRIEVER_ERROR: str | None = None
except Exception as exc:  # missing package, or a bad index path
    retrieve = None  # type: ignore[assignment]
    _RETRIEVER_ERROR = f"{type(exc).__name__}: {exc}"

router = APIRouter(prefix="/assistant", tags=["assistant"])

class AskRequest(BaseModel):
    question: str

#GROUNDED_THRESHOLD = 0.8   # tune by printing distances for good/bad questions
GROUNDED_THRESHOLD = 1.20   # Raised from 0.8 to accommodate sentence-transformers L2 distances

router = APIRouter(prefix="/assistant", tags=["assistant"])
"""
@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    return build_service().ask(payload.question)
"""
@router.post("/ask")
def ask(req: AskRequest) :#-> AskResponse:
    if retrieve is None:
        # Same response shape the widget always gets, so it renders the message
        # in a bubble instead of showing a network error.
        return {
            "answer": (
                "The help assistant is not available on this server yet. "
                "Everything else on the site works normally."
            ),
            "sources": [],
            "suggestions": [],
            "grounded": False,
            "detail": _RETRIEVER_ERROR,
        }

    hits = retrieve(req.question, k=5)
    grounded = bool(hits) and hits[0]["distance"] < GROUNDED_THRESHOLD

    if grounded:
        answer = hits[0]["text"]          # best chunk IS the answer
        """context = "\n---\n".join(f"[{h['section']}]{h['text']}" for h in hits)
        prompt = f"Answer the question in your own words based only on this context:\n{context}\nQuestion: {req.question}"
        response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(system_instruction="You are an assistant. Answer the user question in your own words using ONLY the provided context. If the answer cannot be found in the context, say 'I do not have that information.'"),
                )
        answer = response.text"""
        answer = build_service().ask(req.question)
    else:
        answer = ("I couldn't find this in our help centre. "
                  "Try rephrasing, or contact support.")     
        #return build_service().ask(req.question)
    return {
            "answer": answer,
            "sources": [{"section": h["section"], "excerpt": h["text"][:150]} for h in hits],
            "suggestions": [],
            "grounded": grounded,
        }