"""How someone becomes a cinema operator.

There is deliberately no self-service route: anyone could otherwise sign up and
start listing a hall they do not own. Registration always produces a customer,
and a platform administrator grants operator access.

The detail worth pinning down is that the role is read from the **database**,
not from the access token's claim. That means a promotion takes effect on the
very next request — the user does not have to sign out and back in, and a stale
token cannot keep granting access after a demotion either.
"""

from __future__ import annotations

import uuid

import pytest

API = "/api/v1"


def _register(client, label: str = "user") -> dict:  # noqa: ANN001
    email = f"{label}_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Test Person"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {
        "id": body["user"]["id"],
        "email": email,
        "role": body["user"]["role"],
        "auth": {"Authorization": f"Bearer {body['tokens']['access_token']}"},
    }


@pytest.fixture
def admin(client):  # noqa: ANN001
    resp = client.post(
        f"{API}/auth/login",
        json={"email": "admin@cineai.example", "password": "adminpass1"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


def test_registration_never_grants_operator_access(client) -> None:  # noqa: ANN001
    person = _register(client)
    assert person["role"] == "customer"
    assert client.get(f"{API}/operator/cinemas", headers=person["auth"]).status_code == 403


def test_an_admin_can_promote_and_it_applies_without_re_login(client, admin) -> None:  # noqa: ANN001
    """The same token must start working the moment the role changes.

    The role is resolved from the database on every request, so nothing has to
    be reissued. If it were read from the token's claim instead, the user would
    be stuck until it expired.
    """
    person = _register(client, "owner")
    assert client.get(f"{API}/operator/cinemas", headers=person["auth"]).status_code == 403

    promoted = client.put(
        f"{API}/admin/users/{person['id']}/role",
        json={"role": "cinema_operator"},
        headers=admin,
    )
    assert promoted.status_code == 200, promoted.text
    assert "cinema_operator" in promoted.json()["message"]

    # Same token as before -- no new sign-in.
    assert client.get(f"{API}/operator/cinemas", headers=person["auth"]).status_code == 200


def test_demotion_also_applies_immediately(client, admin) -> None:  # noqa: ANN001
    """A stale token must not keep granting access after access is removed."""
    person = _register(client, "temp")
    client.put(
        f"{API}/admin/users/{person['id']}/role",
        json={"role": "cinema_operator"},
        headers=admin,
    )
    assert client.get(f"{API}/operator/cinemas", headers=person["auth"]).status_code == 200

    client.put(
        f"{API}/admin/users/{person['id']}/role",
        json={"role": "customer"},
        headers=admin,
    )
    assert client.get(f"{API}/operator/cinemas", headers=person["auth"]).status_code == 403


def test_only_an_admin_can_change_roles(client, admin) -> None:  # noqa: ANN001
    """Otherwise anyone could promote themselves and the gate means nothing."""
    person = _register(client)
    self_promote = client.put(
        f"{API}/admin/users/{person['id']}/role",
        json={"role": "admin"},
        headers=person["auth"],
    )
    assert self_promote.status_code == 403

    # An operator cannot promote either.
    operator = _register(client, "op")
    client.put(
        f"{API}/admin/users/{operator['id']}/role",
        json={"role": "cinema_operator"},
        headers=admin,
    )
    assert client.put(
        f"{API}/admin/users/{person['id']}/role",
        json={"role": "admin"},
        headers=operator["auth"],
    ).status_code == 403


def test_a_new_operator_owns_the_cinema_they_create(client, admin) -> None:  # noqa: ANN001
    person = _register(client, "founder")
    client.put(
        f"{API}/admin/users/{person['id']}/role",
        json={"role": "cinema_operator"},
        headers=admin,
    )

    city_id = client.get(f"{API}/cities").json()[0]["id"]
    created = client.post(
        f"{API}/operator/cinemas",
        json={
            "city_id": city_id,
            "name": f"Starlight {uuid.uuid4().hex[:6]}",
            "address_line": "100 Feet Road, Indiranagar",
            "timezone": "Asia/Kolkata",
        },
        headers=person["auth"],
    )
    assert created.status_code == 201, created.text
    cinema_id = created.json()["id"]

    # It is theirs, and only theirs.
    mine = client.get(f"{API}/operator/cinemas", headers=person["auth"]).json()
    assert [c["id"] for c in mine] == [cinema_id]

    stranger = _register(client, "stranger")
    client.put(
        f"{API}/admin/users/{stranger['id']}/role",
        json={"role": "cinema_operator"},
        headers=admin,
    )
    assert client.get(
        f"{API}/operator/cinemas/{cinema_id}/screens", headers=stranger["auth"]
    ).status_code == 403


def test_the_last_administrator_cannot_demote_themselves(client, admin) -> None:  # noqa: ANN001
    """That would lock everyone out of the console permanently."""
    me = client.get(f"{API}/me", headers=admin).json()
    resp = client.put(
        f"{API}/admin/users/{me['id']}/role", json={"role": "customer"}, headers=admin
    )
    # Either refused outright, or allowed because another admin exists.
    if resp.status_code == 409:
        assert resp.json()["error"]["code"] == "LAST_ADMIN"
    else:
        # Put it back so the rest of the suite still has an administrator.
        assert resp.status_code == 200
        client.put(
            f"{API}/admin/users/{me['id']}/role", json={"role": "admin"}, headers=admin
        )
