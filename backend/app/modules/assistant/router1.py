from fastapi import APIRouter
from pydantic import BaseModel
from .retriever import retrieve

router = APIRouter(prefix="/assistant", tags=["assistant"])

class AskRequest(BaseModel):
    question: str

GROUNDED_THRESHOLD = 0.8   # tune by printing distances for good/bad questions

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