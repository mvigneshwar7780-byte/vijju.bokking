"""Guest checkout is intentional. Leaking a stranger's ticket is not.

Two separate questions get conflated when a product allows anonymous booking:

1. *Can someone buy without an account?*  Yes, deliberately — every major
   ticketing platform allows it, and forcing registration before payment is a
   conversion decision, not a security one.
2. *What does possession of an identifier entitle you to?*  That depends
   entirely on how guessable the identifier is:

   - A **booking id** is UUIDv7: 48 bits of timestamp plus 74 random bits. Even
     knowing the exact millisecond, finding one is 2^74 guesses. It is safe to
     treat as an unguessable link, which is what guest checkout relies on.
   - A **booking reference** is 8 characters from a 30-character alphabet
     (~2^39), printed on the ticket and quoted aloud. It is an identifier, not
     a credential, and must be paired with something only the owner knows.

The response carries the signed QR payload — the ticket itself — so getting
this wrong hands out free entry.
"""

from __future__ import annotations

import uuid

API = "/api/v1"


def _guest_booking(client, pick_show) -> dict:  # noqa: ANN001
    """A confirmed booking made with no Authorization header at any step."""
    session_key = uuid.uuid4().hex
    show = pick_show(client)
    seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
    row = next(
        r for r in seatmap["rows"] if sum(s["status"] == "available" for s in r["seats"]) >= 6
    )
    seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:2]

    hold = client.post(
        f"{API}/holds",
        json={"show_id": show["id"], "seat_ids": seat_ids, "session_key": session_key},
    )
    assert hold.status_code == 201, hold.text

    booking = client.post(
        f"{API}/bookings",
        json={
            "hold_id": hold.json()["hold_id"],
            "session_key": session_key,
            "contact_email": "guest@example.com",
        },
    )
    assert booking.status_code == 201, booking.text
    booking = booking.json()

    payment = client.post(f"{API}/bookings/{booking['id']}/pay", json={"method": "upi"})
    assert payment.status_code == 200, payment.text
    settled = client.post(
        f"{API}/payments/mock/{payment.json()['gateway_order_id']}/complete",
        params={"outcome": "success"},
    )
    assert settled.json()["status"] == "confirmed", settled.json()
    return booking


def test_guest_can_complete_a_booking_without_an_account(client, pick_show, cleanup_bookings) -> None:  # noqa: ANN001
    """Guest checkout is a supported flow, not an accident."""
    booking = _guest_booking(client, pick_show)
    cleanup_bookings.append(booking["show"]["show_id"])

    confirmed = client.get(f"{API}/bookings/{booking['id']}").json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["qr_payload"], "a guest must still receive their ticket"


def test_reference_alone_does_not_expose_a_booking(client, pick_show, cleanup_bookings) -> None:  # noqa: ANN001
    """The printed reference is an identifier, not a credential."""
    booking = _guest_booking(client, pick_show)
    cleanup_bookings.append(booking["show"]["show_id"])
    reference = booking["booking_reference"]

    # No email at all -> the parameter is required.
    assert client.get(f"{API}/bookings/reference/{reference}").status_code == 422

    # Wrong email -> indistinguishable from "no such reference", so the endpoint
    # cannot be used to confirm that a reference exists.
    wrong = client.get(
        f"{API}/bookings/reference/{reference}", params={"email": "attacker@example.com"}
    )
    assert wrong.status_code == 404
    missing = client.get(
        f"{API}/bookings/reference/CNZZZZZZZZ", params={"email": "attacker@example.com"}
    )
    assert missing.status_code == 404
    assert wrong.json()["error"]["code"] == missing.json()["error"]["code"]


def test_reference_plus_matching_email_returns_the_booking(client, pick_show, cleanup_bookings) -> None:  # noqa: ANN001
    booking = _guest_booking(client, pick_show)
    cleanup_bookings.append(booking["show"]["show_id"])

    resp = client.get(
        f"{API}/bookings/reference/{booking['booking_reference']}",
        params={"email": "GUEST@Example.COM"},  # case-insensitive
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == booking["id"]
    assert resp.json()["qr_payload"]


def test_a_signed_in_user_cannot_read_someone_elses_booking(client, pick_show, cleanup_bookings) -> None:  # noqa: ANN001
    """An owned booking is visible only to its owner, guest flow or not."""
    email = f"owner_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Owner"},
    )
    owner_auth = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

    session_key = uuid.uuid4().hex
    show = pick_show(client)
    cleanup_bookings.append(show["id"])
    seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
    row = next(
        r for r in seatmap["rows"] if sum(s["status"] == "available" for s in r["seats"]) >= 6
    )
    seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:2]

    hold = client.post(
        f"{API}/holds",
        json={"show_id": show["id"], "seat_ids": seat_ids, "session_key": session_key},
        headers=owner_auth,
    ).json()
    booking = client.post(
        f"{API}/bookings",
        json={"hold_id": hold["hold_id"], "session_key": session_key, "contact_email": email},
        headers=owner_auth,
    ).json()

    intruder = client.post(
        f"{API}/auth/register",
        json={
            "email": f"intruder_{uuid.uuid4().hex[:8]}@example.com",
            "password": "hunter2pass",
            "full_name": "Intruder",
        },
    )
    intruder_auth = {"Authorization": f"Bearer {intruder.json()['tokens']['access_token']}"}

    assert client.get(f"{API}/bookings/{booking['id']}", headers=intruder_auth).status_code == 403
    assert client.get(f"{API}/bookings/{booking['id']}").status_code == 403
    assert client.get(f"{API}/bookings/{booking['id']}", headers=owner_auth).status_code == 200
