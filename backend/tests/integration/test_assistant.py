"""The assistant endpoint's contract.

These test the wiring, not the answers: the route is reachable, guests may use
it, the response has the shape the widget renders, and input is bounded. They
are written to stay true once a real answer engine replaces the stub in
``service.py`` -- if implementing ``ask`` breaks one of these, it broke the
contract the frontend depends on.

Answer *quality* is untested on purpose. There is nothing answering yet.
"""

from __future__ import annotations

API = "/api/v1"


def test_guest_can_reach_the_assistant(client) -> None:  # noqa: ANN001
    """No login required.

    The questions a help assistant exists for -- refund windows, what a format
    costs -- are asked *before* someone has an account.
    """
    resp = client.post(f"{API}/assistant/ask", json={"question": "how do refunds work?"})
    assert resp.status_code == 200, resp.text


def test_reply_has_the_shape_the_widget_renders(client) -> None:  # noqa: ANN001
    """The four fields ChatWidget.tsx draws. Adding or dropping one breaks it."""
    body = client.post(f"{API}/assistant/ask", json={"question": "anything"}).json()

    assert set(body) == {"answer", "sources", "suggestions", "grounded"}
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["sources"], list)
    assert isinstance(body["suggestions"], list)
    assert isinstance(body["grounded"], bool)


def test_sources_carry_a_section_and_an_excerpt(client) -> None:  # noqa: ANN001
    """Whatever engine is wired in, a citation is (section, excerpt)."""
    body = client.post(f"{API}/assistant/ask", json={"question": "anything"}).json()
    for source in body["sources"]:
        assert set(source) == {"section", "excerpt"}


def test_empty_question_is_rejected(client) -> None:  # noqa: ANN001
    assert client.post(f"{API}/assistant/ask", json={"question": ""}).status_code == 422


def test_overlong_question_is_rejected(client) -> None:  # noqa: ANN001
    """Bounded input: whatever is wired in will be handed this string."""
    resp = client.post(f"{API}/assistant/ask", json={"question": "x" * 501})
    assert resp.status_code == 422


def test_missing_question_field_is_rejected(client) -> None:  # noqa: ANN001
    assert client.post(f"{API}/assistant/ask", json={}).status_code == 422
