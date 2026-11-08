import re
from pathlib import Path
import lancedb
from sentence_transformers import SentenceTransformer

"""HERE = Path(__file__).parent
CORPUS = HERE / "movie_booking_vector_embedding_corpus.txt"   # relative, not C:/Users/...
DB_PATH = str(HERE.parent.parent.parent / "lancedb_help")     # backend/lancedb_help
MODEL_NAME = "all-MiniLM-L6-v2"

def chunk_by_headings(md: str) -> list[dict]:
    parts = re.split(r"(?m)^((?:##|###)\s+.+)$", md)
    chunks, current_title = [], "(start)"
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## ") or part.startswith("### "):
            current_title = part.lstrip("# ").strip()
            continue
        if len(part) < 60:
            continue
        chunks.append({"section": current_title, "text": part})
    return chunks

def main():
    text = CORPUS.read_text(encoding="utf-8")
    chunks = chunk_by_headings(text)
    model = SentenceTransformer(MODEL_NAME)
    vectors = model.encode([c["text"] for c in chunks], normalize_embeddings=True)
    rows = [{"section": c["section"], "text": c["text"], "vector": v.tolist()}
            for c, v in zip(chunks, vectors)]
    db = lancedb.connect(DB_PATH)
    if "policy_chunks" in db.table_names():
        db.drop_table("policy_chunks")
    db.create_table("policy_chunks", data=rows)
    print(f"Ingested {len(rows)} chunks")

if __name__ == "__main__":
    main()"""

#__________________________________________________________________________________________

from langchain_text_splitters import RecursiveCharacterTextSplitter

HERE = Path(__file__).parent
CORPUS = HERE / "movie_policies.txt"
DB_PATH = str(HERE.parent.parent.parent / "lancedb_help")
TABLE_NAME = "policy_chunks"
MODEL_NAME = "all-MiniLM-L6-v2"

def chunk_by_text(md: str, chunk_size: int = 10000, chunk_overlap: int = 300) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    
    raw_chunks = splitter.split_text(md)
    chunks: list[dict] = []
    for i, text in enumerate(raw_chunks):
        match = re.search(r"^(#{1,3}\s+.+)", text.strip())
        section_name = match.group(1).lstrip("#").strip() if match else f"Chunk_{i + 1}"
        
        chunks.append({
            "section": section_name,
            "text": text.strip()
        })
        
    return chunks

def main():
    if not CORPUS.exists():
        raise FileNotFoundError(f"Corpus file not found: {CORPUS}")
        
    text = CORPUS.read_text(encoding="utf-8")
    chunks = chunk_by_text(text, chunk_size=10000, chunk_overlap=300)
    
    model = SentenceTransformer(MODEL_NAME)
    texts = [c["text"] for c in chunks]
    vectors = model.encode(texts, normalize_embeddings=True)
    
    rows = [
        {
            "section": chunks[i]["section"],
            "text": chunks[i]["text"],
            "vector": vectors[i].tolist()
        }
        for i in range(len(chunks))
    ]
    
    db = lancedb.connect(DB_PATH)
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)
    db.create_table(TABLE_NAME, data=rows)
    print(f"Successfully ingested {len(rows)} chunks into {TABLE_NAME}")

if __name__ == "__main__":
    main()