import os
import re
from dotenv import load_dotenv
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_protocol import Literal, NotRequired
#from langgraph import add_nodes, add_edges
#from langgraph import visualize_graph
from langgraph.graph import StateGraph , START, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.checkpoint.memory import InMemorySaver 
from typing_extensions import TypedDict
#-----------------------------------------------------------
from pathlib import Path
import lancedb
import shutil
import numpy as np
import pandas as pd
from typing import Any
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter


BASE_DIR = Path.cwd()
#POLICY_PATH = Path("C:\\Users\\Admin\\Documents\\GitHub\\SimpleAgentProject\\ag\\movie_booking_vector_embedding_corpus.txt")
POLICY_PATH = Path("C:\\Users\\Admin\\Documents\\GitHub\\SimpleAgentProject\\ag\\movie_policies")

policy_text = POLICY_PATH.read_text(encoding="utf-8")
"""
def chunk_by_text(md: str) -> list[dict]:
    #split on markdown headers, keeping the heading text,
    #this is intentionally simple for teaching.
    parts = re.split(r"(?m)^((?:##|###)\s+.+)$", md)
    chunks: list[dict] = []
    current_title = "(start)"

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("##") or part.startswith("###"):
            current_title = part.lstrip("#").strip()
            continue
        text = part.strip()
        if len(text) <60:
            continue
        chunks.append({
            "section": current_title,
            "text": text
        })
    chunks = RecursiveCharacterTextSplitter(
         chunk_size = 1000,
         chunk_overlap = 150,
         separators=["\n\n","\n",". "," ",""]
    )

    return chunks

policy_chunks = chunk_by_text(policy_text)

MODEL_NAME = "all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_NAME)

def search_file(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    query_embedding = model.encode(query)
    db = lancedb.connect(BASE_DIR / "movie_booking_vector_embedding_corpus.lancedb")
    collection = db.get_table("movie_booking_vector_embedding_corpus")
    results = collection.search(query_embedding, "embedding", limit=top_k).to_list()
    return results

DB_PATH = str(BASE_DIR / "lancedb_kodekloud_airline")
TABLE_NAME = "policy_chunks"
if Path(DB_PATH).exists():
    import shutil
    shutil.rmtree(DB_PATH)

db = lancedb.connect(DB_PATH)

texts = [c["text"] for c in policy_chunks]
sections = [c["section"] for c in policy_chunks]
vectors = model.encode(texts, normalize_embeddings=True)
rows = [
    {"section": sections[i], "text": texts[i], "embedding": vectors[i].tolist()}
    for i in range(len(texts))
]

if TABLE_NAME in db.table_names():
    db.drop_table(TABLE_NAME)
tbl = db.create_table(TABLE_NAME, data=rows)

def search_chunks(query: str, top_k: int = 3) -> pd.DataFrame:
    query_emb = model.encode(query, normalize_embeddings=True).tolist() 
    df = (
        #tbl.search(query_emb, "embedding", top_k)
        tbl.search(query_emb).limit(top_k)
        .to_pandas()
    )
    cols = [c for c in df.columns if c in {"section", "text", "_distance", "score"}]
    return df[cols]
def get_answer_from_chunks(query: str, top_k: int = 3) -> str:
    df = search_chunks(query, top_k)
    
    context = "\n\n".join(f"Section: {row['section']}\nText: {row['text']}" for _, row in df.iterrows())
    prompt = (
        f"You are a helpful assistant. Based on the following context, answer the question.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\nAnswer:"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content"""
# ---------------------------------------------------------------------------
# Chunking with chunk_size and chunk_overlap
# ---------------------------------------------------------------------------
def chunk_by_text(md: str, chunk_size: int = 10000, chunk_overlap: int = 300) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    
    # 1. Perform standard chunking
    raw_chunks = splitter.split_text(md)
    
    # 2. Package into dictionaries with "text" and "section" to match downstream code
    chunks: list[dict] = []
    for i, text in enumerate(raw_chunks):
        # Optional: Attempt to extract heading if chunk starts with markdown header
        match = re.search(r"^(#{1,3}\s+.+)", text.strip())
        section_name = match.group(1).lstrip("#").strip() if match else f"Chunk_{i + 1}"
        
        chunks.append({
            "section": section_name,
            "text": text.strip()
        })
        
    return chunks


policy_chunks = chunk_by_text(policy_text, chunk_size=10000, chunk_overlap=300)

# ---------------------------------------------------------------------------
# Embedding Model & LanceDB Setup
# ---------------------------------------------------------------------------
MODEL_NAME = "all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_NAME)

DB_PATH = str(BASE_DIR / "lancedb_movie_policies")
TABLE_NAME = "policy_chunks"

if Path(DB_PATH).exists():
    shutil.rmtree(DB_PATH)

db = lancedb.connect(DB_PATH)

texts = [c["text"] for c in policy_chunks]
sections = [c["section"] for c in policy_chunks]
vectors = model.encode(texts, normalize_embeddings=True)

rows = [
    {
        "section": sections[i],
        "text": texts[i],
        "vector": vectors[i].tolist()   # LanceDB defaults to "vector" for embeddings
    }
    for i in range(len(texts))
]

tbl = db.create_table(TABLE_NAME, data=rows)

# ---------------------------------------------------------------------------
# Retrieval & Generation
# ---------------------------------------------------------------------------
def search_chunks(query: str, top_k: int = 7) -> pd.DataFrame:
    query_emb = model.encode(query, normalize_embeddings=True).tolist()
    
    # Search table using query vector
    df = (
        tbl.search(query_emb)
        .limit(top_k)
        .to_pandas()
    )
    cols = [c for c in df.columns if c in {"section", "text", "_distance", "score"}]
    return df[cols]


def get_answer_from_chunks(query: str, top_k: int = 7) -> str:
    df = search_chunks(query, top_k)
    
    context = "\n\n".join(
        f"Section: {row['section']}\nText: {row['text']}" 
        for _, row in df.iterrows()
    )
    #print(context)
    prompt = (
        f"You are a helpful assistant. Based on the following context, answer the question.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\nAnswer:"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    #return response.content
    return context

#--------------------------------------------------------------
load_dotenv()

# Database credentials
DB_USER = os.getenv("POSTGRES_USER", "avnadmin")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "AVNS_g0BOSC8jDawaxrGWTfz")
DB_HOST = os.getenv("POSTGRES_HOST", "pg-368ac8e6-mudhireddynandu-664d.h.aivencloud.com")
DB_PORT = os.getenv("POSTGRES_PORT", "19798")
DB_NAME = os.getenv("POSTGRES_DB", "defaultdb")

DATABASE_URI = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?sslmode=require"
)

# 1. Connect and inspect schema
db = SQLDatabase.from_uri(DATABASE_URI)

class chartState(TypedDict):
    message: list


def sql_query_generator(user_question: str) -> str:
    """Generates a SQL query from a user question using the LLM."""
    # Step 1: User question -> SQL Query
    query_generator = (
        {
            "question": lambda x: x["question"],
            "schema": lambda _: db.get_table_info()
        }
        | sql_prompt
        | llm
        | StrOutputParser()
        | clean_sql_query
    )
    return query_generator.invoke({"question": user_question})
# 2. Initialize Gemini Model

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
   # google_api_key= os.getenv("AQ.Ab8RN6K-a5-9bsaLULrqyNdbktWN8PWoonDKyZg1II5Bdv3gbw"),
   #google_api_key= "AQ.Ab8RN6K-a5-9bsaLULrqyNdbktWN8PWoonDKyZg1II5Bdv3gbw",
   #google_api_key = "AQ.Ab8RN6Koa3NC4niDtAx6c_tjkqX68vhGJGr38rX5Cv00-oiWCA",
   #google_api_key = "AQ.Ab8RN6LC6bPWIkRuCw8tD-WOxbKw5ttzEeeDG9SKkdxSzeRhOQ",
  # google_api_key = "AQ.Ab8RN6K-WwxCOGZIuCrxzrbjV5icUbXtMHhM6gjkczdDz76Odg",
    #temperature=0
)

# 3. Prompt for generating SQL queries
sql_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a PostgreSQL expert. Given an input question, create a syntactically "
        "correct PostgreSQL SELECT query to run. Return ONLY the raw SQL query without "
        "any markdown fences, comments, or explanations.\n\n"
        "Here is the database schema:\n{schema}"
    )),
    ("user", "{question}")
])

def clean_sql_query(query_output: str) -> str:
    """Strips markdown code fences and unnecessary whitespace."""
    text = str(query_output)
    cleaned = re.sub(r"```(sql)?", "", text)
    return cleaned.strip("` \n;") + ";"

# Step 1: User question -> SQL Query
query_generator = (
    {
        "question": lambda x: x["question"],
        "schema": lambda _: db.get_table_info()
    }
    | sql_prompt
    | llm
    | StrOutputParser()
    | clean_sql_query
)

# Tool to execute the query
execute_tool = QuerySQLDataBaseTool(db=db)

# Step 2: Answer prompt synthesizing the question and SQL data
synthesis_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant. Use the question, SQL query, and query result to provide a clear answer."),
    ("user", "Question: {question}\nSQL Query: {query}\nSQL Result: {result}\nAnswer:")
])

# Full pipeline
full_chain = (
    RunnablePassthrough.assign(query=query_generator)
    .assign(result=lambda x: execute_tool.invoke(x["query"]))
    | synthesis_prompt
    | llm
    | StrOutputParser()
)

def query_database(user_question: str) -> str:
    return full_chain.invoke({"question": user_question})

"""if __name__ == "__main__":
    #question = "List all table names and display 3 rows from one table."
    question = input("Enter your question for the database: ")
    print("Sending query to database...")
    answer = query_database(question)
    print("\n--- Database Response ---")
    print(answer)

    app = chartState.compile()

    out1 = app.invoke({"question":input("Enter the question : ")})
    print ("Intent: " , out1.get("intent"))
    print(out1.get("final_answer"))"""
 #   __________________________________________________

class chartState(TypedDict):
        question: str
        classify_state: NotRequired[Literal["sql","answer"]]
        sql_query: NotRequired[str]
        db_result: NotRequired[str]
        final_answer: NotRequired[str]
        file_answer: NotRequired[str]
        chunk_final_answer: NotRequired[str]
        sql_final_answer: NotRequired[str]
        generate_answer: NotRequired[str]
        answer_question: NotRequired[str]


chartState = StateGraph(chartState)
def classify_state(state: chartState) -> dict:

        """prompt = (
            "classify the question into exactly one of the following intents: 'sql' or 'answer'. " \
            "If the question needed for a SQL query to be generated to answer it , classify it as 'sql'. " \
            "If the question can be answered based on the knowledge result, classify it as 'answer'. " \
            "here is the question: {question}\n"
            "return only intent in "
        )
        resp = client.responses.create(
             model="gemini-3.6-flash",
             instructions = "your are a strict classifier.",
             input = prompt,
        )"""
        question = state.get("question","")
        classification_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a strict classifier. Classify the user query into exactly one of "
        "the following intents: 'sql' or 'answer'.\n"
        "- If answering requires querying a SQL database, return 'sql'.\n"
        "- If it can be answered using general knowledge without a database query, return 'answer'.\n"
        "Return ONLY the intent name in lowercase with no punctuation or extra text."
    ),
    ("human", "{question}")
])
        label=classification_prompt|llm|StrOutputParser()

        #label = (resp.output_text or "").strip().lower()
        label :str = label.invoke(question)
        label = label.strip().lower()
        label = "sql" if "sql" in label else "answer"
    
        return {"classify_state" : label}
    
def generate_sql_query(state: chartState) -> dict:
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
        "schema": lambda _: db.get_table_info()
    }
    | sql_prompt
    | llm
    | StrOutputParser()
    | clean_sql_query
)
            return {"sql_query": query_generator.invoke({"question": state["question"]})}      
    

def generate_answer(state: chartState) -> dict:
    # Tool to execute the query
    execute_tool = QuerySQLDataBaseTool(db=db)
    result = execute_tool.invoke(state["sql_query"])
    return {"db_result": result}

def sql_final_answer(state: chartState) -> dict:
    synthesis_prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant. Use the question, SQL query, and query result to provide a clear answer."),
        ("user", "Question: {question}\nSQL Query: {sql_query}\nSQL Result: {db_result}\nAnswer:")
    ])
    """full_chain = (
        RunnablePassthrough.assign(query=state["sql_query"])
        .assign(result=lambda x: execute_tool.invoke(x["query"]))
        | synthesis_prompt
        | llm
        | StrOutputParser()
    )
    return {"sql_final_answer": full_chain.invoke({"question": state["question"]})}"""
    chain = synthesis_prompt | llm | StrOutputParser()
    answer = chain.invoke({
        "question": state["question"],
        "sql_query": state["sql_query"],
        "db_result": state["db_result"]
    })
    return {"sql_final_answer": answer}

def answer_question(state: chartState) -> dict:
  # 1. Retrieve the extra context
  answer = get_answer_from_chunks(state["question"])

  # 2. Assign the prompt template to a variable
  prompt_template = ChatPromptTemplate.from_messages([
      (
          "system",
          (
              "You are a strict answerer. Answer the given question based on"
              " the given information. If the information is not sufficient to"
              " answer the question, say 'I don't know'."
          ),
      ),
      (
          "human",
          (
              "Here is the question: {question}\n"
              "Here is the information: {db_result}\n"
              "Additional context: {answer}"
          ),
      ),
  ])

  # 3. Build the Runnable chain using the prompt template variable
  chain = prompt_template | llm | StrOutputParser()

  # 4. Invoke the chain with your dictionary of inputs
  result = chain.invoke({
      "question": state["question"],
      "db_result": state.get("db_result", ""),
      "answer": answer,
  })

  return {"answer_question": result or "I don't know."}

def chunk_file_answer(state: chartState) -> dict:
    answer = get_answer_from_chunks(state["question"])

    prompt = (
            f"You are a helpful assistant. Based on the following context, answer the question.\n\n"
            f"Context:\n{answer}\n\n"
            f"Question: {state["question"]}\nAnswer:"
        )
    response = llm.invoke([HumanMessage(content=prompt)])
    result= response.content



    #return {"chunk_final_answer": answer}
    #return {"chunk_final_answer":  np.array2string(answer[:10], precision=3)}
    #return {"chunk_final_answer": np.array2string(np.asarray(answer[:10]), precision=3)}
    return {"chunk_final_answer": result[0]["text"]}

def final_answer(state: chartState) -> dict:
    label = state.get("classify_state","answer")
    if label == "sql" :
        #return {"final_answer": state["sql_final_answer"]}
        return {"final_answer": state["answer_question"]}
    elif label == "answer" :
        return {"final_answer": state["chunk_final_answer"]}
    else:
        return {"final_answer": "I don't know."}

chartState.add_node("classify_state", classify_state)
chartState.add_node("generate_sql_query", generate_sql_query)
#chartState.add_edges("classify_state", "generate_sql_query", condition=lambda x: x["classify_state"] == "sql")
chartState.add_node("sql_final_answer", sql_final_answer)
chartState.add_node("generate_answer", generate_answer)
#chartState.add_edges("generate_sql_query", "sql_final_answer")
chartState.add_node("answer_question", answer_question)
chartState.add_node("chunk_file_answer",chunk_file_answer)
chartState.add_node("final_answer", final_answer)
#chartState.add_edges("classify_state", "file_answer", condition=lambda x: x["classify_state"] == "answer")
chartState.add_edge(START, "classify_state")

def route_by_intent(state: chartState) :
    return state.get("classify_state", "answer")

chartState.add_conditional_edges(
    "classify_state",
    route_by_intent,
    path_map = {
        "sql": "generate_sql_query",
        "answer": "chunk_file_answer"
    }
)

chartState.add_edge("generate_sql_query", "generate_answer")
#chartState.add_edge("generate_answer", "sql_final_answer")

chartState.add_edge("generate_answer","answer_question")

#chartState.add_edge("sql_final_answer","final_answer")

chartState.add_edge("answer_question","final_answer")

chartState.add_edge("chunk_file_answer","final_answer")
chartState.add_edge("final_answer",END)
app = chartState.compile()

if __name__ == "__main__":
    #question = "List all table names and display 3 rows from one table."
    """question = input("Enter your question for the database: ")
    print("Sending query to database...")
    answer = query_database(question)
    print("\n--- Database Response ---")
    print(answer)"""

    app = chartState.compile()

    out1 = app.invoke({"question":input("______Enter the question________ : ")})
    print ("--------------------Intent:-------------------: " , out1.get("classify_state"))
    print("-----------------final_answer : ",out1.get("final_answer"), "\n ",
#          "------------------sql_query : ",out1.get("sql_query"),"\n",
#          "------------------db_result : ",out1.get("db_result"),"\n"
          )
from IPython.display import Image, display

# Pass the raw PNG bytes directly
"""png_data = app.get_graph().draw_mermaid_png()
display(Image(data=png_data))"""
"""with open("graph.png", "wb") as f:
    f.write(app.get_graph().draw_mermaid_png())"""
import io
from PIL import Image

# Read raw bytes directly into memory and display
png_bytes = app.get_graph().draw_mermaid_png()
img = Image.open(io.BytesIO(png_bytes))
img.show()