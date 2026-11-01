"""from langchain.community.document_loader import webBaseLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chromadb import Chroma
from langchain.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import requests

Google_API_Key = "AQ.Ab8RN6K-a5-9bsaLULrqyNdbktWN8PWoonDKyZg1II5Bdv3gbw"
llm = ChatGoogleGenerativeAI(model = "gemini-3.6-flash", temperature = 0.2, google_api_key = Google_API_Key)

prompt_template = ChatPromptTemplate.from_messages(
[
(
"system",
"You are a helpful assistant that can tell the name of the last movies based on what the user give.",
),
(
"human",
"Output ONLY the exact movie title."

"If the title is already explicitly mentioned in the text, extract and output just that title."

"Do not include any explanations, punctuation, quotation marks, introductory text, or pleasantries. Only return the title."
"and here is the info: {movie_title}",
),
]
)

api_key = "ee18bf0"
def get_imdb_rating(movie_title: str):
    url = "https://www.omdbapi.com/"
    params = {
        "t": movie_title, "apikey": "ee18bf0"
    }
    
    response = requests.get(url, params=params)
    data = response.json()
   # print(data.get("imdbRating", "Rating not found"))
    #print(f"Fetching IMDB rating for: {movie_title}")
    return data.get("imdbRating", "Rating not found")
"""def get_imdb_info(data):
    question = input("what do you want to know about the movie? ")
    prompt_template = ChatPromptTemplate.from_messages(
                    [
                    (
                    "system",
                    "You are a helpful assistant that can tell the name of the last movies based on what the user give.",
                    ),
                    (
                    "human",
                    "answer the question based on the info given, if you don't know the answer, say 'I don't know'."
                    "and here is the info: {data} \n\n question: {question}",
                    ),
                    ]
                    )
    return prompt_template | llm
    
"""

movie = input("Enter the movie title: ")
rag_chain = prompt_template | llm | StrOutputParser()|get_imdb_rating #|get_imdb_info|StrOutputParser
answer = rag_chain.invoke({"movie_title": movie})
print(answer)