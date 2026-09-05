"""Request and response models for the support assistant."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.schemas import APIModel


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class Source(APIModel):
    """The passage an answer was drawn from, so the reply is checkable."""

    section: str
    excerpt: str


class AskResponse(APIModel):
    answer: str
    sources: list[Source]
    suggestions: list[str]
    # False when nothing in the knowledge base matched well enough to answer.
    # The frontend uses this to present the reply as a miss rather than a fact.
    grounded: bool
