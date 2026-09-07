import re
from pathlib import Path
import lancedb
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).parent
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
    main()