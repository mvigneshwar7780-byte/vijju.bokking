import os
import re
from pathlib import Path

import lancedb
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
BASE_DIR = Path.cwd()
POLICY_PATH = Path("C:/Users/Admin/Documents/booking/vijju.bokking/backend/app/db/seed/movie_booking_vector_embedding_corpus.txt")

policy_text = POLICY_PATH.read_text(encoding="utf-8")
print(f"Loaded policy: {POLICY_PATH.name}")
print(f"Characters: {len(policy_text):,}")

print("\n--- Preview (first 400 chars) ---\n")
print(policy_text[:400])
def chunk_by_headings(md: str) -> list[dict]:
    # Split on markdown headings, keeping the heading text.
    # This is intentionally simple for teaching.
    parts = re.split(r"(?m)^((?:##|###)\s+.+)$", md)

    chunks: list[dict] = []
    current_title = "(start)"

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if part.startswith("## ") or part.startswith("### "):
            current_title = part.lstrip("# ").strip()
            continue

        text = part.strip()
        if len(text) < 60:
            continue

        chunks.append({
            "section": current_title,
            "text": text,
        })

    return chunks

chunks = chunk_by_headings(policy_text)
print(f"Chunks: {len(chunks)}")
print("\nExample chunk:")
print("Section:", chunks[0]["section"])
print("Text (first 250 chars):\n", chunks[0]["text"][:250])
MODEL_NAME = "all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_NAME)

example = "What is the cabin baggage limit?"
v = model.encode(example)
print("Model:", MODEL_NAME)
print("Vector shape:", v.shape)
print("Vector preview:", np.array2string(v[:10], precision=3))
DB_PATH = str(BASE_DIR / "lancedb_kodekloud_airline")
TABLE_NAME = "policy_chunks"

# Recreate DB folder each run for a clean demo (optional).
# If you want persistence between runs, comment out the next 2 lines.
if Path(DB_PATH).exists():
    import shutil
    shutil.rmtree(DB_PATH)

db = lancedb.connect(DB_PATH)

texts = [c["text"] for c in chunks]
sections = [c["section"] for c in chunks]

vectors = model.encode(texts, normalize_embeddings=True)
rows = [
    {"section": sections[i], "text": texts[i], "vector": vectors[i].tolist()}
    for i in range(len(texts))
]

if TABLE_NAME in db.table_names():
    db.drop_table(TABLE_NAME)

tbl = db.create_table(TABLE_NAME, data=rows)
print("Rows in table:", tbl.count_rows())
def search_policy(question: str, k: int = 3) -> pd.DataFrame:
    qvec = model.encode(question, normalize_embeddings=True).tolist()
    df = (
        tbl.search(qvec)
        .limit(k)
        .to_pandas()
    )
    # LanceDB returns a distance/score column; keep the view clean for teaching.
    cols = [c for c in df.columns if c in {"section", "text", "_distance", "score"}]
    return df[cols]

def pretty_print_results(question: str, k: int = 2, preview_chars: int = 500) -> None:
    print("Question:", question)
    results = search_policy(question, k=k)
    for i, row in results.iterrows():
        section = row.get("section", "")
        text = row.get("text", "")
        dist = row.get("_distance", None)
        print("\n--- Match", i + 1, "---")
        if dist is not None:
            print("Distance:", float(dist))
        print("Section:", section)
        print(text[:preview_chars])
pretty_print_results("how can I get the refund?", k=4)
pretty_print_results("can I bring a pet?", k=4)
pretty_print_results("can I cancel my booking?", k=4)