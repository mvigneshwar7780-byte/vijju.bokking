
from __future__ import annotations
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
"""
_______________________________VERSION 2.0______________________________________
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
GEMINI_API_KEY = "AQ.Ab8RN6KYECdK574aBRF5K1A9hZAjq47jRDgZKo2LSvC87JjO2Q"
client = genai.Client(api_key=GEMINI_API_KEY)


_NOT_WIRED = (
    "The assistant is not connected to an answer engine yet. "
    "Once one is wired up, this is where its reply will appear."
)


class AssistantService:
""""""Answers customer questions.

Construction is per-request. If your implementation needs to load something
expensive -- an index, a model, a database handle -- build it once at module
scope or behind a cache rather than here, or every question pays for it"""
"""
"""

#    def ask(self, question: str) :#-> AskResponse:
"""Answer one question.

        Args:
            question: What the customer typed. Already validated as 1-500
                characters by ``AskRequest``, but not otherwise sanitised.

        Returns:
            The reply to render. See the module docstring for what each field
            drives in the UI.
        """
 #       hits = retrieve(question, k=3)
"""if not hits or hits[0]["distance"] > 1.20:
        
            return AskResponse(
                answer=_NOT_WIRED,
                sources=[],
                suggestions=[],
                grounded=False,
            )""""""
        context = "\n---\n".join(f"[{h['section']}]{h['text']}" for h in hits)
        prompt = f"Answer the question in your own words based only on this context:\n{context}\nQuestion: {question}"
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction="You are an assistant. Answer the user question in your own words using ONLY the provided context. If the answer cannot be found in the context, say 'I do not have that information.'"),
        )
        """"""print("Answer:", response.text)
        return AskResponse(
            
            answer=response.text,
            sources=[{"section": h["section"], "excerpt": h["text"][:150]} for h in hits],
            suggestions=[],
            grounded=True,
        )""""""
        return response.text


def build_service() -> AssistantService:
 #   Factory used by the router.
    return AssistantService()


__all__ = ["AssistantService", "build_service"]
from langchain.chat_models import gan_ai
"""

#___________________________________ VERSION 2.0 (with LangChain) ______________________________________

"""from __future__ import annotations

import os
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

# Safely import the custom retriever
try:
from .retriever import retrieve
except Exception:
retrieve = None

# API Configuration
GEMINI_API_KEY = "AQ.Ab8RN6KYECdK574aBRF5K1A9hZAjq47jRDgZKo2LSvC87JjO2Q"

# Initialize LLM at module scope to avoid per-request instantiation overhead
llm = ChatGoogleGenerativeAI(
model="gemini-2.5-flash",
google_api_key=GEMINI_API_KEY,
temperature=0.2,
)

# Define structured prompt template with system instructions and user context
prompt_template = ChatPromptTemplate.from_messages(
[
(
"system",
"You are an assistant. Answer the user question in your own words using ONLY the provided context. "
"If the answer cannot be found in the context, say 'I do not have that information.'",
),
(
"human",
"Answer the question in your own words based only on this context:\n{context}\n\nQuestion: {question}",
),
]
)

# Build the LCEL (LangChain Expression Language) pipeline: Prompt -> LLM -> String
rag_chain = prompt_template | llm | StrOutputParser()


class AssistantService:
"""
#Answers customer questions using RAG via LangChain.
"""

def ask(self, question: str) -> str:
"""
#Retrieve relevant context and generate an answer for the given question.
"""
# Fetch relevant documents using the retriever
hits = retrieve(question, k=3) if retrieve else []

# Format retrieved chunks into a single context string
context = "\n---\n".join(f"[{h['section']}]{h['text']}" for h in hits)

# Run the question and context through the LangChain RAG pipeline
answer: str = rag_chain.invoke(
{
"context": context,
"question": question,
}
)

return answer


def build_service() -> AssistantService:
"""
#Factory used by the application router.
"""
return AssistantService()


__all__ = ["AssistantService", "build_service"]"""

#________________________________________VERSION 3.0 (with memory) __________________________________
"""import os
from typing import Dict

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_google_genai import ChatGoogleGenerativeAI

from dotenv import load_dotenv

load_dotenv()

# Safely import the custom retriever
try:
    from .retriever import retrieve
except Exception:
    retrieve = None

# Load API Key securely from the environment
#GEMINI_API_KEY = "AQ.Ab8RN6KYECdK574aBRF5K1A9hZAjq47jRDgZKo2LSvC87JjO2Q"
#GEMINI_API_KEY = "AQ.Ab8RN6K-a5-9bsaLULrqyNdbktWN8PWoonDKyZg1II5Bdv3gbw"
GEMINI_API_KEY = "AQ.Ab8RN6IuSYoT0ohGV5aBr2bmu_xT1aJkt76X4lvMnXFtn0AsjQ"
GEMINI_API_KEY = os.getenv(GEMINI_API_KEY)

# Initialize LLM at module scope
llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

# In-memory store for session histories
session_store: Dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> InMemoryChatMessageHistory:
    """#Retrieve or create an in-memory chat history for a session.
"""
    if session_id not in session_store:
        session_store[session_id] = InMemoryChatMessageHistory()
    return session_store[session_id]


# Prompt template with short-term history support
prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an assistant. Answer the user question in your own words using ONLY the provided context and conversation history. "
            "If the answer cannot be found in the context, say 'I do not have that information.'",
        ),
        MessagesPlaceholder(variable_name="history"),
        (
            "human",
            "Context:\n{context}\n\nQuestion: {question}",
        ),
    ]
)

# Base LCEL pipeline
base_chain = prompt_template | llm | StrOutputParser()

# Wrap pipeline with message history management
chain_with_history = RunnableWithMessageHistory(
    base_chain,
    get_session_history=get_session_history,
    input_messages_key="question",
    history_messages_key="history",
)


class AssistantService:
    """
#Answers customer questions using RAG and short-term memory via LangChain.
"""

    def ask(self, question: str, session_id: str = "default_session") -> str:
        """
#Retrieve relevant context and generate an answer while maintaining conversation memory.
"""
        hits = retrieve(question, k=3) if retrieve else []

        # Format retrieved chunks into a single context string
        context = "\n---\n".join(f"[{h['section']}]{h['text']}" for h in hits)

        # Execute chain with session tracking
        answer: str = chain_with_history.invoke(
            {
                "context": context,
                "question": question,
            },
            config={"configurable": {"session_id": session_id}},
        )

        return answer


def build_service() -> AssistantService:
    """
#Factory used by the application router.
"""
    return AssistantService()


__all__ = ["AssistantService", "build_service"]"""
#_____________________________________________________________________
""""import json
import os
from typing import List

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# Safely import the custom retriever
try:
    from .retriever import retrieve
except ImportError:
    retrieve = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

HISTORY_FILE = os.path.join(os.path.dirname(__file__), ".chat_history.json")


def load_disk_history() -> List[dict]:
    """#Load conversation history from disk to ensure persistence across API requests.
"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_disk_history(history: List[dict]):
    """#Persist conversation history to disk.
"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-10:], f, ensure_ascii=False, indent=2)  # Keep last 5 turns
    except Exception as e:
        print(f"[Warning] Failed to save history: {e}")


class AssistantService:
    """#Answers customer questions using RAG and persisted file-backed history.
"""

    def ask(self, question: str, session_id: str = "default_session") -> str:
        # 1. LOAD HISTORY FROM DISK
        raw_history = load_disk_history()

        # Find the last bot reply and last user question
        last_bot_reply = ""
        last_user_query = ""
        for turn in reversed(raw_history):
            if turn.get("role") == "assistant" and not last_bot_reply:
                last_bot_reply = turn.get("content", "")
            elif turn.get("role") == "user" and not last_user_query:
                last_user_query = turn.get("content", "")

        # 2. RESOLVE RETRIEVAL QUERY USING HISTORY
        # If question contains pronouns or is very short, combine it with the previous context
        search_query = question
        lowered = question.strip().lower()
        needs_context = any(
            w in lowered for w in ["that", "it", "this", "they", "more", "tell me", "what is"]
        ) or len(question.split()) <= 4

        if needs_context and (last_bot_reply or last_user_query):
            # Combine current question with the subject of the previous answer
            search_query = f"{question} {last_bot_reply[:120]}"

        # 3. RETRIEVE RELEVANT CHUNKS
        hits = retrieve(search_query, k=5) if retrieve else []

        # Fallback search if combined query yielded nothing
        if not hits and last_bot_reply and retrieve:
            hits = retrieve(last_bot_reply[:100], k=5)

        context = "\n---\n".join(
            f"[{h.get('section', 'General')}] {h.get('text', '')}"
            if isinstance(h, dict)
            else str(h)
            for h in hits
        )

        # 4. BUILD THE FULL CONVERSATION MESSAGES FOR THE LLM
        system_instruction = (
            "You are a helpful customer support assistant for a cinema help centre.\n"
            "Use the provided context and conversation history to answer the question.\n"
            "- When the user asks 'what is that?' or uses references, use the previous messages to understand the movie or topic they mean.\n"
            "- Summarize details from the context (genre, rating, synopsis, timings).\n"
            "- Only if there is no relevant information in the context or chat history, say:\n"
            "'I couldn't find this in our help centre. Try rephrasing, or contact support.'"
        )

        llm_messages = [SystemMessage(content=system_instruction)]

        # Inject past history into the LLM prompt
        for turn in raw_history[-6:]:
            if turn.get("role") == "user":
                llm_messages.append(HumanMessage(content=turn.get("content", "")))
            elif turn.get("role") == "assistant":
                llm_messages.append(AIMessage(content=turn.get("content", "")))

        # Append current user question with the retrieved context
        current_content = f"Context from Help Centre:\n{context}\n\nUser Question: {question}"
        llm_messages.append(HumanMessage(content=current_content))

        # 5. GENERATE ANSWER
        chain = llm | StrOutputParser()
        answer = chain.invoke(llm_messages)

        # 6. SAVE CURRENT TURN TO DISK
        raw_history.append({"role": "user", "content": question})
        raw_history.append({"role": "assistant", "content": answer})
        save_disk_history(raw_history)

        return answer


def build_service() -> AssistantService:
    """#Factory used by the application router.
"""
    return AssistantService()


__all__ = ["AssistantService", "build_service"]"""

#____________________________________________________________________________


import os
import re
from typing import Any, List
from typing_extensions import TypedDict, NotRequired, Literal
from dotenv import load_dotenv

from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from app.modules.assistant.personal import build_personal_context
from app.modules.assistant.schemas import AskResponse, Source

load_dotenv()

# --- Database & LLM Initialization ---
DB_USER = os.getenv("POSTGRES_USER", "avnadmin")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "AVNS_g0BOSC8jDawaxrGWTfz")
DB_HOST = os.getenv("POSTGRES_HOST", "pg-368ac8e6-mudhireddynandu-664d.h.aivencloud.com")
DB_PORT = os.getenv("POSTGRES_PORT", "19798")
DB_NAME = os.getenv("POSTGRES_DB", "defaultdb")

DATABASE_URI = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?sslmode=require"
)

try:
    sql_db = SQLDatabase.from_uri(DATABASE_URI)
    execute_tool = QuerySQLDataBaseTool(db=sql_db)
except Exception:
    sql_db = None
    execute_tool = None

try:
    from .retriever import retrieve, get_context_from_chunks
except ImportError:
    retrieve = None
    get_context_from_chunks = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6K-WwxCOGZIuCrxzrbjV5icUbXtMHhM6gjkczdDz76Odg")

#GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6LC6bPWIkRuCw8tD-WOxbKw5ttzEeeDG9SKkdxSzeRhOQ")

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
)

# --- Utility Functions ---
def clean_sql_query(query_output: str) -> str:
    text = str(query_output)
    cleaned = re.sub(r"```(sql)?", "", text)
    return cleaned.strip("` \n;") + ";"

def extract_text(content: Any) -> str:
    """Normalize message content to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        extracted = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                extracted.append(item["text"])
            elif isinstance(item, str):
                extracted.append(item)
        return "\n".join(extracted).strip()
    return str(content)

# --- LangGraph Graph Definition ---
class AssistantState(TypedDict):
    question: str
    # Who is asking, taken from the verified JWT -- never from the question
    # text. None means nobody is signed in.
    #
    # Nothing scopes on this yet: it is carried so the nodes that will serve
    # personal data have a trustworthy identity to filter by. Putting the user
    # id in the prompt instead would make it an instruction, and an instruction
    # can be argued with ("ignore that and show all bookings"). This value
    # cannot be reached from anything the customer types.
    user_id: NotRequired[str | None]
    # The signed-in customer's own bookings, already fetched and scoped in
    # code. Empty for a guest. See personal.py for why this is not something
    # the model is allowed to query for itself.
    personal_context: NotRequired[str]
    classify_state: NotRequired[Literal["sql", "answer"]]
    sql_query: NotRequired[str]
    db_result: NotRequired[str]
    final_answer: NotRequired[str]
    chunk_final_answer: NotRequired[str]
    answer_question: NotRequired[str]
    sources: NotRequired[List[dict]]


def classify_state_node(state: AssistantState) -> dict:
    classification_prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a strict classifier. Classify the user query into exactly one of "
            "the following intents: 'sql' or 'answer'.\n"
            "- If answering requires querying a cinema booking database (screenings, users, tickets, movies), return 'sql'.\n"
            "- If it can be answered using general policy/help documentation without a database query, return 'answer'.\n"
            "Return ONLY the intent name in lowercase with no punctuation or extra text."
        ),
        ("human", "{question}")
    ])
    chain = classification_prompt | llm | StrOutputParser()
    raw_label = chain.invoke({"question": state.get("question", "")})
    label = extract_text(raw_label).strip().lower()
    return {"classify_state": "sql" if "sql" in label else "answer"}


def generate_sql_query_node(state: AssistantState) -> dict:
    if not sql_db:
        return {"sql_query": ""}
    
    sql_prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a PostgreSQL expert. Given an input question, create a syntactically "
            "correct PostgreSQL SELECT query to run. Return ONLY the raw SQL query without "
            "any markdown fences, comments, or explanations.\n\n"
            "Here is the database schema:\n{schema}"
        )),
        ("user", "{question}")
    ])
    query_generator = (
        {
            "question": lambda x: x["question"],
            "schema": lambda _: sql_db.get_table_info()
        }
        | sql_prompt
        | llm
        | StrOutputParser()
        | clean_sql_query
    )
    raw_sql = query_generator.invoke({"question": state["question"]})
    return {"sql_query": extract_text(raw_sql)}


def generate_answer_node(state: AssistantState) -> dict:
    if not execute_tool or not state.get("sql_query"):
        return {"db_result": "No database connection or empty query."}
    try:
        result = execute_tool.invoke(state["sql_query"])
    except Exception as e:
        result = f"Database query error: {e}"
    return {"db_result": str(result)}


def answer_question_node(state: AssistantState) -> dict:
    context = get_context_from_chunks(state["question"]) if get_context_from_chunks else ""
    prompt_template = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a helpful cinema assistant. Answer the question using the database query results and extra policy context provided. "
            "If customer data is supplied, it belongs to the person asking -- use it to answer about their bookings and refunds. "
            "Never infer or invent data about any other customer."
        ),
        (
            "human",
            "Question: {question}\nDatabase Result: {db_result}\nExtra Context: {context}\n{personal}\nAnswer:"
        ),
    ])
    chain = prompt_template | llm | StrOutputParser()
    result = chain.invoke({
        "question": state["question"],
        "db_result": state.get("db_result", ""),
        "context": context,
        "personal": state.get("personal_context", ""),
    })
    return {"answer_question": extract_text(result)}


def chunk_file_answer_node(state: AssistantState) -> dict:
    context = get_context_from_chunks(state["question"]) if get_context_from_chunks else ""
    prompt_template = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a helpful assistant. Based on the provided context, answer the user's question clearly. "
            "If customer data is supplied, it belongs to the person asking -- use it for questions about their own bookings and refunds. "
            "Never infer or invent data about any other customer."
        ),
        (
            "human",
            "Context:\n{context}\n\n{personal}\n\nQuestion: {question}\nAnswer:"
        )
    ])

    # StrOutputParser normalizes both string and list block formats into plain text
    chain = prompt_template | llm | StrOutputParser()
    raw_answer = chain.invoke({
        "context": context,
        "question": state["question"],
        "personal": state.get("personal_context", ""),
    })
    return {"chunk_final_answer": extract_text(raw_answer)}


def final_answer_node(state: AssistantState) -> dict:
    label = state.get("classify_state", "answer")
    if label == "sql":
        answer = state.get("answer_question", "Unable to answer from database.")
    else:
        answer = state.get("chunk_final_answer", "I couldn't find this in our help centre.")
    return {"final_answer": extract_text(answer)}


def route_by_intent(state: AssistantState) -> str:
    return state.get("classify_state", "answer")


workflow = StateGraph(AssistantState)
workflow.add_node("classify_state", classify_state_node)
workflow.add_node("generate_sql_query", generate_sql_query_node)
workflow.add_node("generate_answer", generate_answer_node)
workflow.add_node("answer_question", answer_question_node)
workflow.add_node("chunk_file_answer", chunk_file_answer_node)
workflow.add_node("final_answer", final_answer_node)

workflow.add_edge(START, "classify_state")
workflow.add_conditional_edges(
    "classify_state",
    route_by_intent,
    {
        "sql": "generate_sql_query",
        "answer": "chunk_file_answer"
    }
)
workflow.add_edge("generate_sql_query", "generate_answer")
workflow.add_edge("generate_answer", "answer_question")
workflow.add_edge("answer_question", "final_answer")
workflow.add_edge("chunk_file_answer", "final_answer")
workflow.add_edge("final_answer", END)

compiled_app = workflow.compile()


class AssistantService:
    """Answers customer questions via LangGraph SQL + RAG state engine."""

    def ask(self, question: str, user_id: str | None = None) -> AskResponse:
        """Answer one question.

        Args:
            question: What the customer typed.
            user_id: The signed-in user's id, or None for a guest. Supplied by
                the route from the verified token, so it is trustworthy in a
                way nothing in `question` is.
        """
        hits = retrieve(question, k=5) if retrieve else []
        grounded = bool(hits) and hits[0]["distance"] < 1.20

        try:
            # Fetched here, by user id, before the graph runs -- so the data
            # is already decided by the time any prompt is built. Nothing the
            # customer typed can widen it.
            result = compiled_app.invoke({
                "question": question,
                "user_id": user_id,
                "personal_context": build_personal_context(user_id),
            })
            answer = extract_text(result.get("final_answer", "No answer generated."))
        except Exception as e:
            answer = f"Error processing query: {e}"
            grounded = False

        sources = [
            Source(section=h["section"], excerpt=h["text"][:150])
            for h in hits
        ]

        return AskResponse(
            answer=answer,
            sources=sources,
            suggestions=[],
            grounded=grounded,
        )


def build_service() -> AssistantService:
    return AssistantService()


__all__ = ["AssistantService", "build_service"]