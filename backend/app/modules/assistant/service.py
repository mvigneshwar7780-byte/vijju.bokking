"""Where the assistant's answers come from.

**This is a stub. Implementing `ask` is the whole job.**

Everything around it is finished and will not need to change: the widget, the
`POST /assistant/ask` route, and the response contract in `schemas.py`. Return an
`AskResponse` from here and it renders.

The four fields exist because the widget already draws them:

``answer``
    The reply text. Rendered as the chat bubble; newlines are preserved.
``sources``
    Where the answer came from. Rendered as an expandable "N sources"
    disclosure under the bubble. Return ``[]`` and the disclosure is not drawn.
``suggestions``
    Follow-up questions, rendered as clickable chips that ask themselves.
``grounded``
    ``False`` marks the reply as a miss rather than a fact -- the bubble gets a
    warning border. Use it when nothing was found, so the UI never presents a
    guess as an answer.

`ask` is called once per question and is given no conversation history: the
transcript lives in the browser. If you want multi-turn context, add it to
`AskRequest` in `schemas.py` and send it from `ChatWidget.tsx`.
"""

from __future__ import annotations

from app.modules.assistant.schemas import AskResponse

_NOT_WIRED = (
    "The assistant is not connected to an answer engine yet. "
    "Once one is wired up, this is where its reply will appear."
)


class AssistantService:
    """Answers customer questions.

    Construction is per-request. If your implementation needs to load something
    expensive -- an index, a model, a database handle -- build it once at module
    scope or behind a cache rather than here, or every question pays for it.
    """

    def ask(self, question: str) -> AskResponse:
        """Answer one question.

        Args:
            question: What the customer typed. Already validated as 1-500
                characters by ``AskRequest``, but not otherwise sanitised.

        Returns:
            The reply to render. See the module docstring for what each field
            drives in the UI.
        """
        return AskResponse(
            answer=_NOT_WIRED,
            sources=[],
            suggestions=[],
            grounded=False,
        )


def build_service() -> AssistantService:
    """Factory used by the router."""
    return AssistantService()


__all__ = ["AssistantService", "build_service"]
