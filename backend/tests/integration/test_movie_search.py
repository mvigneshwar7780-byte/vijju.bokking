"""Catalogue browse and keyword search.

`GET /movies?q=…` returned a 500 for its entire existence, so the home-page
search box and the operator's film picker were both dead. The cause was a
combination that reads as harmless: a many-to-many join forces SELECT DISTINCT,
and PostgreSQL then refuses `ORDER BY similarity(title, :q)` because a DISTINCT
query may only order by expressions in its select list.

It only failed when a search term was supplied *and* the ranking clause was
added, which is why plain browsing looked fine. These tests cover both paths.
"""

from __future__ import annotations

import uuid

import pytest

API = "/api/v1"


def test_browsing_without_a_search_term_works(client) -> None:  # noqa: ANN001
    resp = client.get(f"{API}/movies", params={"status": "now_showing"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] > 0
    assert len(body["items"]) > 0


@pytest.fixture
def a_seeded_title(client) -> str:  # noqa: ANN001
    """A real title from the live catalogue.

    Hardcoding one ("Iron Meridian") meant every search test broke the day the
    demo catalogue was replaced -- a failure that said nothing about search. The
    behaviour under test is "a query for a title that exists finds it", so the
    title should come from the data, not from a literal.
    """
    items = client.get(f"{API}/movies", params={"status": "now_showing"}).json()["items"]
    assert items, "catalogue is empty; nothing to search for"
    # A multi-word title gives the case-insensitivity and partial-word cases
    # something to bite on.
    return next((m["title"] for m in items if " " in m["title"]), items[0]["title"])


@pytest.mark.parametrize("case", ["lower", "upper", "exact", "first_word"])
def test_keyword_search_returns_results_not_a_500(client, a_seeded_title, case) -> None:  # noqa: ANN001
    """The exact request shape that used to blow up, in four casings."""
    term = {
        "lower": a_seeded_title.lower(),
        "upper": a_seeded_title.upper(),
        "exact": a_seeded_title,
        "first_word": a_seeded_title.split()[0],
    }[case]

    resp = client.get(f"{API}/movies", params={"q": term})
    assert resp.status_code == 200, f"search for {term!r} failed: {resp.text}"
    titles = [m["title"] for m in resp.json()["items"]]
    assert a_seeded_title in titles, f"{term!r} did not find {a_seeded_title!r}: {titles}"


def test_search_is_typo_tolerant(client, a_seeded_title) -> None:  # noqa: ANN001
    """Trigram similarity is the reason pg_trgm is a required extension."""
    # Transpose two characters in the middle of the title.
    mid = len(a_seeded_title) // 2
    typo = a_seeded_title[:mid] + a_seeded_title[mid + 1] + a_seeded_title[mid] + a_seeded_title[mid + 2:]
    assert typo != a_seeded_title, "failed to construct a typo"

    resp = client.get(f"{API}/movies", params={"q": typo})
    assert resp.status_code == 200, resp.text
    titles = [m["title"] for m in resp.json()["items"]]
    assert a_seeded_title in titles, f"typo {typo!r} did not find {a_seeded_title!r}: {titles}"


def test_a_search_with_no_matches_is_an_empty_list_not_an_error(client) -> None:  # noqa: ANN001
    resp = client.get(f"{API}/movies", params={"q": uuid.uuid4().hex})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


def test_search_combines_with_filters(client) -> None:  # noqa: ANN001
    """Filters used to be joins, which is what forced the broken DISTINCT."""
    city_id = client.get(f"{API}/cities").json()[0]["id"]
    resp = client.get(
        f"{API}/movies",
        params={"q": "e", "city_id": city_id, "status": "now_showing"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("genre", ["drama", "action"])
def test_genre_filter_does_not_duplicate_rows(client, genre: str) -> None:  # noqa: ANN001
    """A film in several genres must appear once, not once per genre.

    This is what DISTINCT was papering over; filtering with EXISTS removes the
    duplicates at source instead.
    """
    resp = client.get(f"{API}/movies", params={"genre": genre, "page_size": 100})
    assert resp.status_code == 200, resp.text
    ids = [m["id"] for m in resp.json()["items"]]
    assert len(ids) == len(set(ids)), "the same film was returned more than once"
    assert resp.json()["total"] == len(ids) or resp.json()["has_next"]


def test_language_filter_does_not_duplicate_rows(client) -> None:  # noqa: ANN001
    resp = client.get(f"{API}/movies", params={"language": "en", "page_size": 100})
    assert resp.status_code == 200, resp.text
    ids = [m["id"] for m in resp.json()["items"]]
    assert len(ids) == len(set(ids))


def test_pagination_total_matches_the_filtered_set(client) -> None:  # noqa: ANN001
    """The count is computed separately from the page; they must agree."""
    first = client.get(f"{API}/movies", params={"page_size": 3, "page": 1}).json()
    assert len(first["items"]) <= 3
    assert first["total"] >= len(first["items"])

    everything = client.get(f"{API}/movies", params={"page_size": 100}).json()
    assert everything["total"] == first["total"]
    assert len({m["id"] for m in everything["items"]}) == len(everything["items"])


def test_archived_films_are_not_offered_to_customers(db) -> None:  # noqa: ANN001
    """A retired film must not surface in browse or search.

    `archived` is how a title leaves the catalogue: no showtimes, nothing to
    book. It was still returned by any listing that did not name a status, so a
    keyword search sent customers to a detail page with nothing on it.

    Exercised through the service rather than the HTTP client on purpose: the
    `db` fixture rolls its transaction back, so a write made through it is
    invisible to the TestClient's separate connection -- the assertions would
    pass without proving anything. Same session for the write and the read keeps
    the test honest, and `list_movies` is where the filter actually lives.
    """
    from sqlalchemy import text

    from app.modules.catalog.service import CatalogService

    service = CatalogService(db)

    rows, _ = service.list_movies(status="now_showing", limit=1)
    assert rows, "catalogue is empty; nothing to archive"
    victim = rows[0]
    word = max(victim.title.split(), key=len)

    # Precondition: findable right now, so the assertions below cannot pass for
    # the wrong reason.
    before, _ = service.list_movies(search=word, limit=100)
    assert any(m.id == victim.id for m in before), (
        f"{victim.title!r} was not findable before archiving"
    )

    db.execute(
        text("UPDATE movies SET status = 'archived' WHERE id = CAST(:i AS uuid)"),
        {"i": str(victim.id)},
    )
    db.flush()

    listed, _ = service.list_movies(limit=100)
    assert not any(m.id == victim.id for m in listed), (
        "archived film appeared in an unfiltered listing"
    )

    found, total = service.list_movies(search=word, limit=100)
    assert not any(m.id == victim.id for m in found), (
        f"archived film is still searchable by {word!r}"
    )

    # ...but an explicit request still returns it, for the operator console.
    explicit, _ = service.list_movies(status="archived", limit=100)
    assert any(m.id == victim.id for m in explicit), (
        "asking for archived explicitly should still return them"
    )
