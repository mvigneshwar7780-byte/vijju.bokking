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


@pytest.mark.parametrize("term", ["iron", "Iron", "IRON MERIDIAN", "meridian"])
def test_keyword_search_returns_results_not_a_500(client, term: str) -> None:  # noqa: ANN001
    """The exact request that used to blow up."""
    resp = client.get(f"{API}/movies", params={"q": term})
    assert resp.status_code == 200, f"search for {term!r} failed: {resp.text}"
    titles = [m["title"] for m in resp.json()["items"]]
    assert any("Iron Meridian" in t for t in titles), titles


def test_search_is_typo_tolerant(client) -> None:  # noqa: ANN001
    """Trigram similarity is the reason pg_trgm is a required extension."""
    resp = client.get(f"{API}/movies", params={"q": "Iron Meridain"})  # transposed
    assert resp.status_code == 200, resp.text
    titles = [m["title"] for m in resp.json()["items"]]
    assert any("Iron Meridian" in t for t in titles), titles


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
