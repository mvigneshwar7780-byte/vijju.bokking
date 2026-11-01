from langchain_experimental.text_splitter import SemanticChunker
from langchain_community.embeddings import HuggingFaceEmbeddings
from pathlib import Path

# Use any local or API-based embedding model
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# Configure the semantic chunker
splitter = SemanticChunker(
    embeddings=embeddings,
    breakpoint_threshold_type="percentile",
    breakpoint_threshold_amount=95,
    buffer_size=1
)
POLICY_PATH = Path("C:\\Users\\Admin\\Documents\\GitHub\\SimpleAgentProject\\ag\\movie_policies")
policy_text = POLICY_PATH.read_text(encoding="utf-8")
chunk = splitter.create_documents([policy_text])
print(policy_text)
#print(chunk)
for i, chunks in enumerate(chunk):
    print(f"--- Chunk {i + 1} ---")
    #print(chunks.page_content.strip())
    print(chunks.page_content)