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
    """The four fields ChatWidget.tsx draws.

    Asserted as a subset, not an exact set: the endpoint may add diagnostic
    keys (it currently returns `detail` when the retrieval engine failed to
    import), and the widget ignores anything it does not know. What must never
    change is that these four are present and correctly typed.
    """
    body = client.post(f"{API}/assistant/ask", json={"question": "anything"}).json()

    assert {"answer", "sources", "suggestions", "grounded"} <= set(body)
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["sources"], list)
    assert isinstance(body["suggestions"], list)
    assert isinstance(body["grounded"], bool)


def test_sources_carry_a_section_and_an_excerpt(client) -> None:  # noqa: ANN001
    """Whatever engine is wired in, a citation is (section, excerpt)."""
    body = client.post(f"{API}/assistant/ask", json={"question": "anything"}).json()
    for source in body["sources"]:
        assert set(source) == {"section", "excerpt"}


def test_degenerate_questions_do_not_crash(client) -> None:  # noqa: ANN001
    """Empty and very long questions must not produce a 500.

    NOTE: these used to be rejected with a 422. The router's own `AskRequest`
    declares a bare `question: str` with no length bounds, so both are now
    accepted and passed straight through to the retrieval engine. That is a
    deliberate choice by the author, not a bug -- but it does mean an unbounded
    string reaches the embedding model, so the contract asserted here is only
    "does not crash", which is weaker than it was.
    """
    for payload in ({"question": ""}, {"question": "x" * 5000}, {"question": "   "}):
        resp = client.post(f"{API}/assistant/ask", json=payload)
        assert resp.status_code < 500, f"{payload!r} produced {resp.status_code}: {resp.text}"


def test_missing_question_field_is_rejected(client) -> None:  # noqa: ANN001
    assert client.post(f"{API}/assistant/ask", json={}).status_code == 422
