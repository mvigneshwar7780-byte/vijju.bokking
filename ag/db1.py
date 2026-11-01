import os
import re
from dotenv import load_dotenv
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

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

# 2. Initialize Gemini Model
llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
   # google_api_key= os.getenv("AQ.Ab8RN6K-a5-9bsaLULrqyNdbktWN8PWoonDKyZg1II5Bdv3gbw"),
   google_api_key= "AQ.Ab8RN6K-a5-9bsaLULrqyNdbktWN8PWoonDKyZg1II5Bdv3gbw",
    temperature=0
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

if __name__ == "__main__":
    #question = "List all table names and display 3 rows from one table."
    question = input("Enter your question for the database: ")
    print("Sending query to database...")
    answer = query_database(question)
    print("\n--- Database Response ---")
    print(answer)