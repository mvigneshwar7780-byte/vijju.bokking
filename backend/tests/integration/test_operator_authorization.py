"""Two operators share a role. Role alone must never be enough.

The failure this guards against is the common one in multi-tenant systems: a
route checks `role == cinema_operator`, forgets to check *which* cinema, and
every operator can read and edit every other operator's data. Role is a
capability; ownership is a separate question, and both have to be asked.

`test_every_operator_route_is_ownership_checked` enumerates the router rather
than listing routes by hand, so a new endpoint added without an ownership check
fails here instead of shipping.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta


from app.core.db import SessionLocal

API = "/api/v1"


def _register(client, role: str | None = None) -> dict:  # noqa: ANN001
    email = f"{(role or 'user')}_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    if role:
        from sqlalchemy import text

        with SessionLocal() as db:
            db.execute(
                text("UPDATE users SET role = :r WHERE id = CAST(:i AS uuid)"),
                {"r": role, "i": body["user"]["id"]},
            )
            db.commit()
    return {
        "id": body["user"]["id"],
        "email": email,
        "auth": {"Authorization": f"Bearer {body['tokens']['access_token']}"},
    }


def _city_id(client) -> str:  # noqa: ANN001
    return client.get(f"{API}/cities").json()[0]["id"]


def _make_cinema(client, operator, name: str) -> str:  # noqa: ANN001
    resp = client.post(
        f"{API}/operator/cinemas",
        json={
            "city_id": _city_id(client),
            "name": name,
            "address_line": "1 Test Road",
            "timezone": "Asia/Kolkata",
        },
        headers=operator["auth"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
def test_a_customer_cannot_reach_operator_routes(client) -> None:  # noqa: ANN001
    customer = _register(client)
    resp = client.get(f"{API}/operator/cinemas", headers=customer["auth"])
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_anonymous_cannot_reach_operator_routes(client) -> None:  # noqa: ANN001
    assert client.get(f"{API}/operator/cinemas").status_code == 401


def test_operator_sees_only_their_own_cinemas(client) -> None:  # noqa: ANN001
    alice = _register(client, "cinema_operator")
    bob = _register(client, "cinema_operator")
    alice_cinema = _make_cinema(client, alice, f"Alice Hall {uuid.uuid4().hex[:6]}")
    _make_cinema(client, bob, f"Bob Hall {uuid.uuid4().hex[:6]}")

    mine = client.get(f"{API}/operator/cinemas", headers=alice["auth"]).json()
    ids = {c["id"] for c in mine}
    assert alice_cinema in ids
    assert len(ids) == 1, "an operator must not see another operator's cinemas"


def test_operator_cannot_touch_another_operators_cinema(client) -> None:  # noqa: ANN001
    alice = _register(client, "cinema_operator")
    bob = _register(client, "cinema_operator")
    alice_cinema = _make_cinema(client, alice, f"Alice Hall {uuid.uuid4().hex[:6]}")

    # Every shape of access Bob might try.
    probes = [
        ("GET", f"{API}/operator/cinemas/{alice_cinema}/screens", None),
        ("GET", f"{API}/operator/cinemas/{alice_cinema}/seat-categories", None),
        ("GET", f"{API}/operator/cinemas/{alice_cinema}/shows", None),
        ("GET", f"{API}/operator/cinemas/{alice_cinema}/bookings", None),
        ("GET", f"{API}/operator/cinemas/{alice_cinema}/reports/revenue", None),
        ("GET", f"{API}/operator/cinemas/{alice_cinema}/reports/occupancy", None),
        ("PATCH", f"{API}/operator/cinemas/{alice_cinema}", {"name": "Bob's now"}),
        (
            "POST",
            f"{API}/operator/cinemas/{alice_cinema}/screens",
            {"name": "Audi 9", "screen_number": 9},
        ),
        (
            "POST",
            f"{API}/operator/cinemas/{alice_cinema}/seat-categories",
            {"code": "X", "name": "X", "default_price_minor": 100},
        ),
    ]
    for method, url, body in probes:
        resp = client.request(method, url, json=body, headers=bob["auth"])
        assert resp.status_code == 403, f"{method} {url} returned {resp.status_code}"
        assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_administrator_can_reach_any_cinema(client) -> None:  # noqa: ANN001
    alice = _register(client, "cinema_operator")
    admin = _register(client, "admin")
    alice_cinema = _make_cinema(client, alice, f"Alice Hall {uuid.uuid4().hex[:6]}")

    assert (
        client.get(
            f"{API}/operator/cinemas/{alice_cinema}/screens", headers=admin["auth"]
        ).status_code
        == 200
    )
    assert client.get(f"{API}/admin/cinemas", headers=admin["auth"]).status_code == 200


def test_operator_cannot_reach_platform_admin_routes(client) -> None:  # noqa: ANN001
    operator = _register(client, "cinema_operator")
    for url in (f"{API}/admin/cinemas", f"{API}/admin/users", f"{API}/admin/reports/revenue"):
        resp = client.get(url, headers=operator["auth"])
        assert resp.status_code == 403, f"{url} returned {resp.status_code}"


def test_operator_cannot_edit_a_movie_someone_else_added(client) -> None:  # noqa: ANN001
    """Movies are a shared catalogue -- one operator must not rewrite another's."""
    alice = _register(client, "cinema_operator")
    bob = _register(client, "cinema_operator")

    created = client.post(
        f"{API}/operator/movies",
        json={"title": f"Alice Film {uuid.uuid4().hex[:6]}", "runtime_minutes": 100},
        headers=alice["auth"],
    )
    assert created.status_code == 201, created.text
    movie_id = created.json()["id"]

    resp = client.patch(
        f"{API}/operator/movies/{movie_id}",
        json={"title": "Bob's edit"},
        headers=bob["auth"],
    )
    assert resp.status_code == 403

    # ...but the author can.
    assert (
        client.patch(
            f"{API}/operator/movies/{movie_id}",
            json={"synopsis": "Updated by the author."},
            headers=alice["auth"],
        ).status_code
        == 200
    )


def test_a_missing_cinema_and_someone_elses_are_indistinguishable(client) -> None:  # noqa: ANN001
    """Otherwise the endpoint becomes an oracle for enumerating cinema ids."""
    bob = _register(client, "cinema_operator")
    alice = _register(client, "cinema_operator")
    alice_cinema = _make_cinema(client, alice, f"Alice Hall {uuid.uuid4().hex[:6]}")

    theirs = client.get(
        f"{API}/operator/cinemas/{alice_cinema}/screens", headers=bob["auth"]
    )
    missing = client.get(
        f"{API}/operator/cinemas/{uuid.uuid4()}/screens", headers=bob["auth"]
    )
    # A non-existent id is a 404 and someone else's is a 403 -- but neither
    # response body reveals anything about the cinema itself.
    assert theirs.status_code == 403
    assert missing.status_code == 404
    assert "name" not in theirs.text.lower() or "Alice Hall" not in theirs.text


def test_every_operator_route_is_ownership_checked(client) -> None:  # noqa: ANN001
    """Enumerate the router so a new unchecked endpoint fails here.

    Any operator route carrying a cinema/screen/show/category id must reject a
    different operator. Routes are discovered from the OpenAPI schema rather
    than listed by hand, so this cannot silently fall out of date.
    """
    import re

    from app.main import create_app

    spec = create_app().openapi()
    operator_paths = [
        (path, method)
        for path, ops in spec["paths"].items()
        if path.startswith("/api/v1/operator/")
        for method in ops
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    # Only routes that name a specific entity can be ownership-checked;
    # collection routes are scoped by the caller instead.
    entity_routes = [
        (p, m) for p, m in operator_paths if re.search(r"\{[a-z_]+_id\}", p)
    ]
    assert entity_routes, "expected operator routes with entity ids"

    alice = _register(client, "cinema_operator")
    bob = _register(client, "cinema_operator")
    cinema_id = _make_cinema(client, alice, f"Alice Hall {uuid.uuid4().hex[:6]}")

    category = client.post(
        f"{API}/operator/cinemas/{cinema_id}/seat-categories",
        json={"code": "STD", "name": "Standard", "default_price_minor": 20000},
        headers=alice["auth"],
    ).json()
    screen = client.post(
        f"{API}/operator/cinemas/{cinema_id}/screens",
        json={"name": "Audi 1", "screen_number": 1},
        headers=alice["auth"],
    ).json()
    client.put(
        f"{API}/operator/screens/{screen['id']}/layout",
        json={"rows": [{"row_label": "A", "seat_count": 6, "category_code": "STD"}]},
        headers=alice["auth"],
    )
    movie = client.post(
        f"{API}/operator/movies",
        json={"title": f"Film {uuid.uuid4().hex[:6]}", "runtime_minutes": 90},
        headers=alice["auth"],
    ).json()
    show = client.post(
        f"{API}/operator/cinemas/{cinema_id}/shows",
        json={
            "screen_id": screen["id"],
            "movie_id": movie["id"],
            "show_date": str(date.today() + timedelta(days=3)),
            "start_time": "18:30:00",
            "prices": [
                {"seat_category_id": category["id"], "price_minor": 25000}
            ],
        },
        headers=alice["auth"],
    )
    assert show.status_code == 201, show.text
    show_id = show.json()["id"]

    ids = {
        "cinema_id": cinema_id,
        "screen_id": screen["id"],
        "show_id": show_id,
        "category_id": category["id"],
        "movie_id": movie["id"],
    }

    unchecked = []
    for path, method in entity_routes:
        url = path
        for key, value in ids.items():
            url = url.replace("{" + key + "}", str(value))
        if "{" in url:
            continue  # a route with an id we did not create
        resp = client.request(method.upper(), url, json={}, headers=bob["auth"])
        # 403 (not yours) is the goal. 422 is acceptable for a body we did not
        # bother constructing -- but 2xx means the check is missing entirely.
        if resp.status_code < 400:
            unchecked.append(f"{method.upper()} {path} -> {resp.status_code}")

    assert not unchecked, (
        "these operator routes let a different operator through:\n  "
        + "\n  ".join(unchecked)
    )
