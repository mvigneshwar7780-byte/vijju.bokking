from functools import lru_cache
import lancedb
from sentence_transformers import SentenceTransformer
from app.db.seed.ingest_help import DB_PATH, MODEL_NAME

@lru_cache(maxsize=1)
def _model():
    return SentenceTransformer(MODEL_NAME)

@lru_cache(maxsize=1)
def _table():
    return lancedb.connect(DB_PATH).open_table("policy_chunks")

def retrieve(question: str, k: int = 3) -> list[dict]:
    qvec = _model().encode(question, normalize_embeddings=True).tolist()
    df = _table().search(qvec).limit(k).to_pandas()
    return [
        {"section": r["section"], "text": r["text"], "distance": float(r["_distance"])}
        for _, r in df.iterrows()
    ]