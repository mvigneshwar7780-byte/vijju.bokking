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
from google import genai
from google.genai import types
from google.genai.errors import ServerError
try:
    from .retriever import retrieve

    _RETRIEVER_ERROR: str | None = None
except Exception as exc:  # missing package, or a bad index path
    retrieve = None  # type: ignore[assignment]
    _RETRIEVER_ERROR = f"{type(exc).__name__}: {exc}"

from app.modules.assistant.schemas import AskResponse
GEMINI_API_KEY = "AQ.Ab8RN6K0jziso02WEgWuUde589qBAmuRlQRiABfyUf3NIju5ug"
client = genai.Client(api_key=GEMINI_API_KEY)


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

    def ask(self, question: str) :#-> AskResponse:
        """Answer one question.

        Args:
            question: What the customer typed. Already validated as 1-500
                characters by ``AskRequest``, but not otherwise sanitised.

        Returns:
            The reply to render. See the module docstring for what each field
            drives in the UI.
        """
        hits = retrieve(question, k=3)
        """if not hits or hits[0]["distance"] > 1.20:
        
            return AskResponse(
                answer=_NOT_WIRED,
                sources=[],
                suggestions=[],
                grounded=False,
            )"""
        context = "\n---\n".join(f"[{h['section']}]{h['text']}" for h in hits)
        prompt = f"Answer the question in your own words based only on this context:\n{context}\nQuestion: {question}"
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction="You are an assistant. Answer the user question in your own words using ONLY the provided context. If the answer cannot be found in the context, say 'I do not have that information.'"),
        )
        """print("Answer:", response.text)
        return AskResponse(
            
            answer=response.text,
            sources=[{"section": h["section"], "excerpt": h["text"][:150]} for h in hits],
            suggestions=[],
            grounded=True,
        )"""
        return response.text


def build_service() -> AssistantService:
    """Factory used by the router."""
    return AssistantService()


__all__ = ["AssistantService", "build_service"]
