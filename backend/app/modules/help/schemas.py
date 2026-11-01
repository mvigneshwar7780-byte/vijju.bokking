"""Response models for the help centre."""

from __future__ import annotations

from app.core.schemas import APIModel


class HelpSection(APIModel):
    category: str
    category_label: str
    title: str
    # Stable anchor. An assistant citation links to /help#<slug>, which is what
    # ties the chatbot's sources back to the page they came from.
    slug: str
    body: list[str]


class HelpCentre(APIModel):
    sections: list[HelpSection]
    # Category order as the page should render it, derived from the corpus
    # rather than hardcoded in the frontend.
    categories: list[str]


class LegalClause(APIModel):
    number: str        # "1.2"
    title: str
    slug: str          # anchor, e.g. /terms#1-2-account-security
    body: list[str]


class LegalArticle(APIModel):
    number: str        # "1"
    title: str
    slug: str
    clauses: list[LegalClause]


class LegalDocument(APIModel):
    articles: list[LegalArticle]
