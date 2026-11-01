"""Help centre endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.help.content import category_label, load_sections
from app.modules.help.legal import load_articles
from app.modules.help.schemas import (
    HelpCentre,
    HelpSection,
    LegalArticle,
    LegalClause,
    LegalDocument,
)

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/sections", response_model=HelpCentre)
def sections() -> HelpCentre:
    """Every published policy, FAQ and format explainer.

    Open to guests, like the assistant that answers from the same source: these
    are the questions people ask *before* they have an account.

    Returned whole rather than paginated -- it is a few dozen short sections,
    and the page renders a table of contents over all of them, so a second
    request would buy nothing.
    """
    loaded = load_sections()
    seen: list[str] = []
    for section in loaded:
        if section.category not in seen:
            seen.append(section.category)

    return HelpCentre(
        sections=[
            HelpSection(
                category=s.category,
                category_label=category_label(s.category),
                title=s.title,
                slug=s.slug,
                body=list(s.body),
            )
            for s in loaded
        ],
        categories=seen,
    )


@router.get("/terms", response_model=LegalDocument)
def terms() -> LegalDocument:
    """The terms of service and related policies, with their numbering intact.

    Separate from `/help/sections`: that endpoint serves the operational rules a
    customer looks up mid-booking and shares a source with the assistant. This
    is the formal document -- navigated by its numbering rather than searched,
    so the article/clause hierarchy is preserved rather than flattened.
    """
    return LegalDocument(
        articles=[
            LegalArticle(
                number=a.number,
                title=a.title,
                slug=a.slug,
                clauses=[
                    LegalClause(
                        number=c.number, title=c.title, slug=c.slug, body=list(c.body)
                    )
                    for c in a.clauses
                ],
            )
            for a in load_articles()
        ]
    )
