"""Every documented demo account must actually be able to sign in.

Seeding a user bypasses the API's Pydantic validation -- the row is written
directly. So an address the seed happily stores can still be one that
`EmailStr` rejects at the login endpoint, and the account is then permanently
unusable: it exists, and every sign-in returns 422 "The request payload is
invalid".

That is exactly what `@cineai.local` did. `.local` is a reserved special-use
TLD (RFC 6762) and `email-validator` refuses it. The README advertised those
credentials. This test closes the loop between what is seeded and what the API
will accept.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.db.seed.loader import SEED_USERS
from app.modules.identity.schemas import LoginRequest

API = "/api/v1"


@pytest.mark.parametrize("email,_name,_role,password", SEED_USERS, ids=[u[0] for u in SEED_USERS])
def test_seeded_account_passes_request_validation(
    email: str, _name: str, _role: object, password: str
) -> None:
    """The address must survive EmailStr before it ever reaches the database."""
    try:
        LoginRequest(email=email, password=password)
    except ValidationError as exc:  # pragma: no cover - the failure is the message
        pytest.fail(f"seeded address {email!r} is rejected by the login schema: {exc}")


@pytest.mark.parametrize("email,_name,_role,password", SEED_USERS, ids=[u[0] for u in SEED_USERS])
def test_seeded_account_can_log_in(
    client, email: str, _name: str, _role: object, password: str
) -> None:  # noqa: ANN001
    resp = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, (
        f"{email} could not sign in: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    assert body["user"]["email"] == email
    assert body["tokens"]["access_token"]

    # And the issued token must actually work.
    me = client.get(
        f"{API}/me", headers={"Authorization": f"Bearer {body['tokens']['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == email
