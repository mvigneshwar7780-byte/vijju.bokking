"""A cancelled seat must be sellable again.

This is the case the happy path never reaches: cancel a booking, then have
somebody else book the very same seat. If `booking_seats` guards uniqueness on
`show_seat_id` alone, the second sale collides with the *cancelled* booking's
row and the seat is permanently unsellable -- silently, and only for seats that
were once cancelled.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.db import SessionLocal

API = "/api/v1"


def _register(client) -> tuple[dict, dict]:  # noqa: ANN001
    email = f"rebook_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Rebooker"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["user"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


def _book(client, auth, user, show_id, seat_ids, session_key) -> dict:  # noqa: ANN001
    hold = client.post(
        f"{API}/holds",
        json={"show_id": show_id, "seat_ids": seat_ids, "session_key": session_key},
        headers=auth,
    )
    assert hold.status_code == 201, hold.text
    booking = client.post(
        f"{API}/bookings",
        json={
            "hold_id": hold.json()["hold_id"],
            "session_key": session_key,
            "contact_email": user["email"],
        },
        headers=auth,
    )
    assert booking.status_code == 201, booking.text
    booking = booking.json()

    payment = client.post(
        f"{API}/bookings/{booking['id']}/pay", json={"method": "upi"}, headers=auth
    )
    assert payment.status_code == 200, payment.text
    settled = client.post(
        f"{API}/payments/mock/{payment.json()['gateway_order_id']}/complete",
        params={"outcome": "success"},
    )
    assert settled.json()["status"] == "confirmed", settled.json()
    return booking


def test_seat_can_be_resold_after_cancellation(client, cleanup_bookings, pick_show) -> None:  # noqa: ANN001
    user_a, auth_a = _register(client)
    user_b, auth_b = _register(client)

    # Outside the cancellation cutoff -- this test cancels and then resells.
    show_id = pick_show(client, cancellable=True)["id"]
    cleanup_bookings.append(show_id)

    seatmap = client.get(f"{API}/shows/{show_id}/seatmap").json()
    row = next(
        r for r in seatmap["rows"] if sum(s["status"] == "available" for s in r["seats"]) >= 6
    )
    seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:2]

    # --- customer A books, then cancels -----------------------------------
    booking_a = _book(client, auth_a, user_a, show_id, seat_ids, uuid.uuid4().hex)
    cancelled = client.post(
        f"{API}/bookings/{booking_a['id']}/cancel", json={"reason": "changed plans"},
        headers=auth_a,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # The seats must be back on sale.
    remap = client.get(f"{API}/shows/{show_id}/seatmap").json()
    freed = {
        s["seat_id"]
        for r in remap["rows"]
        for s in r["seats"]
        if s["status"] == "available"
    }
    assert set(seat_ids) <= freed, "cancelled seats were not returned to the pool"

    # --- customer B buys the very same seats ------------------------------
    booking_b = _book(client, auth_b, user_b, show_id, seat_ids, uuid.uuid4().hex)
    assert booking_b["id"] != booking_a["id"]

    confirmed = client.get(f"{API}/bookings/{booking_b['id']}", headers=auth_b).json()
    assert confirmed["status"] == "confirmed"
    assert len(confirmed["seats"]) == 2

    # Exactly one *active* ticket per seat, and it belongs to customer B.
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT bs.show_seat_id, count(*) FILTER (WHERE b.status = 'confirmed')
                  FROM booking_seats bs
                  JOIN bookings b ON b.id = bs.booking_id
                 WHERE b.show_id = CAST(:show AS uuid)
                 GROUP BY bs.show_seat_id
                HAVING count(*) FILTER (WHERE b.status = 'confirmed') > 1
                """
            ),
            {"show": show_id},
        ).all()
    assert rows == [], f"a seat has more than one confirmed ticket: {rows}"
